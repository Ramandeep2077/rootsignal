package dev.rootsignal.alerts.incident;

import dev.rootsignal.alerts.alert.AlertDtos.AlertResponse;
import dev.rootsignal.alerts.alert.Severity;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

public final class IncidentDtos {

	private IncidentDtos() {
	}

	// ---- public API ----

	public record DecisionRequest(@NotBlank @Size(max = 120) String decidedBy, @Size(max = 2000) String comment) {
	}

	public record IncidentSummary(UUID id, String title, IncidentStatus status, Severity severity,
			List<String> affectedServices, long alertCount, Instant firstAlertAt, Instant summarizedAt,
			Instant notifiedAt, Double timeToSummarySeconds, Object rootCauseCategory, Object confidence,
			Instant createdAt) {

		static IncidentSummary from(Incident incident, long alertCount) {
			Map<String, Object> rootCause = incident.getRootCause();
			return new IncidentSummary(incident.getId(), incident.getTitle(), incident.getStatus(),
					incident.getSeverity(), incident.getAffectedServices(), alertCount, incident.getFirstAlertAt(),
					incident.getSummarizedAt(), incident.getNotifiedAt(), timeToSummary(incident),
					rootCause == null ? null : rootCause.get("category"),
					rootCause == null ? null : rootCause.get("confidence"), incident.getCreatedAt());
		}

	}

	public record IncidentDetail(UUID id, String title, IncidentStatus status, Severity severity,
			List<String> affectedServices, String summary, Map<String, Object> rootCause,
			Map<String, Object> proposedAction, List<Map<String, Object>> reasoningTrace, Map<String, Object> llmUsage,
			Map<String, Object> execution, Instant firstAlertAt, Instant summarizedAt, Instant notifiedAt,
			Double timeToSummarySeconds, Instant decidedAt, String decidedBy, String decisionComment,
			Instant createdAt, Instant updatedAt, List<IncidentStatus> allowedTransitions, List<AlertResponse> alerts) {

		static IncidentDetail from(Incident i, List<AlertResponse> alerts) {
			return new IncidentDetail(i.getId(), i.getTitle(), i.getStatus(), i.getSeverity(), i.getAffectedServices(),
					i.getSummary(), i.getRootCause(), i.getProposedAction(), i.getReasoningTrace(), i.getLlmUsage(),
					i.getExecution(), i.getFirstAlertAt(), i.getSummarizedAt(), i.getNotifiedAt(), timeToSummary(i),
					i.getDecidedAt(), i.getDecidedBy(), i.getDecisionComment(), i.getCreatedAt(), i.getUpdatedAt(),
					List.copyOf(i.getStatus().allowedNext()), alerts);
		}

	}

	static Double timeToSummary(Incident incident) {
		if (incident.getSummarizedAt() == null) {
			return null;
		}
		return Duration.between(incident.getFirstAlertAt(), incident.getSummarizedAt()).toMillis() / 1000.0;
	}

	/** Published to Kafka topic {@code incidents.decisions} when a human approves or rejects. */
	public record DecisionEvent(UUID incidentId, String decision, String decidedBy, String comment,
			Map<String, Object> proposedAction, Instant decidedAt) {
	}

	// ---- internal API (agent service -> alert service) ----

	public record CreateIncidentRequest(@NotBlank @Size(max = 300) String title, @NotNull Severity severity,
			@NotEmpty List<@NotBlank String> affectedServices, @NotEmpty @Size(max = 2000) List<@NotNull UUID> alertIds) {
	}

	public record AttachAlertsRequest(@NotEmpty @Size(max = 2000) List<@NotNull UUID> alertIds) {
	}

	public record StatusRequest(@NotNull IncidentStatus status) {
	}

	public record AnalysisRequest(@NotNull IncidentStatus status, @Size(max = 300) String title, Severity severity,
			@NotBlank String summary, Map<String, Object> rootCause, Map<String, Object> proposedAction,
			List<Map<String, Object>> reasoningTrace, Map<String, Object> llmUsage) {
	}

	public record ExecutionRequest(@NotNull Map<String, Object> execution) {
	}

}
