package dev.oncallcopilot.alerts.incident;

import dev.oncallcopilot.alerts.alert.Alert;
import dev.oncallcopilot.alerts.alert.AlertDtos.AlertResponse;
import dev.oncallcopilot.alerts.alert.AlertRepository;
import dev.oncallcopilot.alerts.alert.Severity;
import dev.oncallcopilot.alerts.config.KafkaEventPublisher;
import dev.oncallcopilot.alerts.config.OncallProperties;
import dev.oncallcopilot.alerts.config.PageResponse;
import dev.oncallcopilot.alerts.error.InvalidStateTransitionException;
import dev.oncallcopilot.alerts.error.NotFoundException;
import dev.oncallcopilot.alerts.incident.IncidentDtos.AnalysisRequest;
import dev.oncallcopilot.alerts.incident.IncidentDtos.CreateIncidentRequest;
import dev.oncallcopilot.alerts.incident.IncidentDtos.DecisionEvent;
import dev.oncallcopilot.alerts.incident.IncidentDtos.DecisionRequest;
import dev.oncallcopilot.alerts.incident.IncidentDtos.IncidentDetail;
import dev.oncallcopilot.alerts.incident.IncidentDtos.IncidentSummary;
import java.time.Clock;
import java.time.Instant;
import java.util.Collection;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;

@Service
public class IncidentService {

	private final IncidentRepository incidentRepository;
	private final AlertRepository alertRepository;
	private final ApplicationEventPublisher applicationEvents;
	private final KafkaEventPublisher kafka;
	private final OncallProperties properties;
	private final Clock clock;

	public IncidentService(IncidentRepository incidentRepository, AlertRepository alertRepository,
			ApplicationEventPublisher applicationEvents, KafkaEventPublisher kafka, OncallProperties properties,
			Clock clock) {
		this.incidentRepository = incidentRepository;
		this.alertRepository = alertRepository;
		this.applicationEvents = applicationEvents;
		this.kafka = kafka;
		this.properties = properties;
		this.clock = clock;
	}

	// ---- queries ----

	@Transactional(readOnly = true)
	public PageResponse<IncidentSummary> list(IncidentStatus status, int page, int size) {
		Page<Incident> incidents = incidentRepository.search(status, PageRequest.of(page, size));
		Set<UUID> ids = incidents.getContent().stream().map(Incident::getId).collect(Collectors.toSet());
		Map<UUID, Long> counts = ids.isEmpty() ? Map.of()
				: alertRepository.countByIncidentIds(ids).stream()
						.collect(Collectors.toMap(AlertRepository.IncidentAlertCount::getIncidentId,
								AlertRepository.IncidentAlertCount::getAlertCount));
		return PageResponse.of(incidents, i -> IncidentSummary.from(i, counts.getOrDefault(i.getId(), 0L)));
	}

	@Transactional(readOnly = true)
	public IncidentDetail get(UUID id) {
		Incident incident = find(id);
		List<AlertResponse> alerts = alertRepository.findByIncidentIdOrderByTimestampAsc(id).stream()
				.map(AlertResponse::from).toList();
		return IncidentDetail.from(incident, alerts);
	}

	// ---- human decisions ----

	@Transactional
	public IncidentDetail approve(UUID id, DecisionRequest request) {
		return decide(id, true, request);
	}

	@Transactional
	public IncidentDetail reject(UUID id, DecisionRequest request) {
		return decide(id, false, request);
	}

	private IncidentDetail decide(UUID id, boolean approved, DecisionRequest request) {
		Incident incident = find(id);
		incident.decide(approved, request.decidedBy(), request.comment(), clock.instant());
		applicationEvents.publishEvent(new DecisionEvent(incident.getId(), incident.getStatus().name(),
				incident.getDecidedBy(), incident.getDecisionComment(), incident.getProposedAction(),
				incident.getDecidedAt()));
		return get(id);
	}

	@TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
	void onDecision(DecisionEvent event) {
		kafka.publish(properties.decisionsTopic(), event.incidentId().toString(), event);
	}

	// ---- agent write-back ----

	@Transactional
	public IncidentDetail create(CreateIncidentRequest request) {
		List<Alert> alerts = loadUnassignedAlerts(request.alertIds(), null);
		Instant now = clock.instant();
		Incident incident = new Incident(request.title(), request.severity(), request.affectedServices(),
				earliestReceived(alerts), now);
		incidentRepository.save(incident);
		alerts.forEach(a -> a.assignTo(incident.getId()));
		return get(incident.getId());
	}

	@Transactional
	public IncidentDetail attachAlerts(UUID id, Collection<UUID> alertIds) {
		Incident incident = find(id);
		List<Alert> alerts = loadUnassignedAlerts(alertIds, id);
		Severity highest = alerts.stream().map(Alert::getSeverity).min(Comparator.naturalOrder()).orElse(null);
		Set<String> services = alerts.stream().map(Alert::getService).collect(Collectors.toCollection(HashSet::new));
		incident.absorb(services, highest, earliestReceived(alerts), clock.instant());
		alerts.forEach(a -> a.assignTo(id));
		return get(id);
	}

	@Transactional
	public IncidentDetail updateStatus(UUID id, IncidentStatus status) {
		find(id).transitionTo(status, clock.instant());
		return get(id);
	}

	@Transactional
	public IncidentDetail recordAnalysis(UUID id, AnalysisRequest request) {
		Incident incident = find(id);
		incident.recordAnalysis(request.status(), request.title(), request.severity(), request.summary(),
				request.rootCause(), request.proposedAction(), request.reasoningTrace(), request.llmUsage(),
				clock.instant());
		return get(id);
	}

	@Transactional
	public IncidentDetail markNotified(UUID id) {
		find(id).markNotified(clock.instant());
		return get(id);
	}

	@Transactional
	public IncidentDetail recordExecution(UUID id, Map<String, Object> execution) {
		find(id).recordExecution(execution, clock.instant());
		return get(id);
	}

	private Incident find(UUID id) {
		return incidentRepository.findById(id).orElseThrow(() -> new NotFoundException("Incident " + id + " not found"));
	}

	/** Alerts may only join one incident; re-attaching to the same incident is an idempotent no-op. */
	private List<Alert> loadUnassignedAlerts(Collection<UUID> ids, UUID targetIncident) {
		Set<UUID> wanted = new HashSet<>(ids);
		List<Alert> alerts = alertRepository.findByIdIn(wanted);
		if (alerts.size() != wanted.size()) {
			Set<UUID> found = alerts.stream().map(Alert::getId).collect(Collectors.toSet());
			wanted.removeAll(found);
			throw new IllegalArgumentException("Unknown alert ids: " + wanted);
		}
		List<Alert> conflicting = alerts.stream()
				.filter(a -> a.getIncidentId() != null && !Objects.equals(a.getIncidentId(), targetIncident))
				.toList();
		if (!conflicting.isEmpty()) {
			throw new InvalidStateTransitionException("Alerts already belong to another incident: "
					+ conflicting.stream().map(Alert::getId).toList());
		}
		return alerts;
	}

	private static Instant earliestReceived(List<Alert> alerts) {
		// Time-to-summary is measured from when *we* first saw the incident, which is immune to sender clock skew.
		return alerts.stream().map(Alert::getReceivedAt).min(Comparator.naturalOrder()).orElseThrow();
	}

}
