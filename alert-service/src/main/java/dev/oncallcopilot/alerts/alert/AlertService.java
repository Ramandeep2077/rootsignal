package dev.oncallcopilot.alerts.alert;

import dev.oncallcopilot.alerts.alert.AlertDtos.AlertEvent;
import dev.oncallcopilot.alerts.alert.AlertDtos.AlertRequest;
import dev.oncallcopilot.alerts.config.KafkaEventPublisher;
import dev.oncallcopilot.alerts.config.OncallProperties;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;

@Service
public class AlertService {

	/** Internal event raised inside the ingest transaction and handled only after it commits. */
	record AlertsIngested(List<AlertEvent> events) {
	}

	private final AlertRepository alertRepository;
	private final ApplicationEventPublisher applicationEvents;
	private final KafkaEventPublisher kafka;
	private final OncallProperties properties;
	private final Clock clock;

	public AlertService(AlertRepository alertRepository, ApplicationEventPublisher applicationEvents,
			KafkaEventPublisher kafka, OncallProperties properties, Clock clock) {
		this.alertRepository = alertRepository;
		this.applicationEvents = applicationEvents;
		this.kafka = kafka;
		this.properties = properties;
		this.clock = clock;
	}

	@Transactional
	public Alert ingest(AlertRequest request) {
		return ingestAll(List.of(request)).getFirst();
	}

	@Transactional
	public List<Alert> ingestAll(List<AlertRequest> requests) {
		Instant now = clock.instant();
		List<Alert> alerts = requests.stream()
				.map(r -> new Alert(r.source(), r.service(), r.severity(), r.message(), r.timestamp(), r.labels(), now))
				.toList();
		List<Alert> saved = alertRepository.saveAll(alerts);
		applicationEvents.publishEvent(new AlertsIngested(saved.stream().map(AlertEvent::from).toList()));
		return saved;
	}

	/**
	 * Publish to Kafka only once the alerts are durably stored, so consumers never see an alert
	 * that a rolled-back transaction would have discarded.
	 */
	@TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
	void onAlertsIngested(AlertsIngested ingested) {
		for (AlertEvent event : ingested.events()) {
			// Keyed by service: alerts for one service stay ordered within a partition.
			kafka.publish(properties.alertsTopic(), event.service(), event);
		}
	}

	@Transactional(readOnly = true)
	public Page<Alert> search(String service, UUID incidentId, int page, int size) {
		return alertRepository.search(service, incidentId, PageRequest.of(page, size));
	}

}
