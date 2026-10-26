package dev.oncallcopilot.alerts.alert;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** Request/response shapes for the alerts API. Records keep the wire format separate from the JPA entity. */
public final class AlertDtos {

	private AlertDtos() {
	}

	@Schema(description = "A normalised alert from any monitoring source")
	public record AlertRequest(
			@Schema(example = "prometheus") @NotBlank @Size(max = 64) String source,
			@Schema(example = "checkout") @NotBlank @Size(max = 120)
			@Pattern(regexp = "[a-z0-9][a-z0-9._-]*", message = "must be lowercase letters, digits, '.', '_' or '-'") String service,
			@Schema(example = "HIGH") @NotNull Severity severity,
			@Schema(example = "p99 latency above 2s for 5m") @NotBlank @Size(max = 4000) String message,
			@NotNull Instant timestamp,
			@Size(max = 32) Map<@NotBlank @Size(max = 64) String, @Size(max = 256) String> labels) {
	}

	public record AlertBatchRequest(@NotEmpty @Size(max = 500) List<@Valid @NotNull AlertRequest> alerts) {
	}

	public record AlertResponse(UUID id, String fingerprint, String source, String service, Severity severity,
			String message, Instant timestamp, Instant receivedAt, Map<String, String> labels, UUID incidentId) {

		public static AlertResponse from(Alert alert) {
			return new AlertResponse(alert.getId(), alert.getFingerprint(), alert.getSource(), alert.getService(),
					alert.getSeverity(), alert.getMessage(), alert.getTimestamp(), alert.getReceivedAt(),
					alert.getLabels(), alert.getIncidentId());
		}

	}

	public record AlertBatchResponse(int accepted, List<UUID> ids) {
	}

	/** Event published to Kafka topic {@code alerts.raw}; consumed by the agent service's triage step. */
	public record AlertEvent(UUID id, String fingerprint, String source, String service, Severity severity,
			String message, Instant timestamp, Instant receivedAt, Map<String, String> labels) {

		public static AlertEvent from(Alert alert) {
			return new AlertEvent(alert.getId(), alert.getFingerprint(), alert.getSource(), alert.getService(),
					alert.getSeverity(), alert.getMessage(), alert.getTimestamp(), alert.getReceivedAt(),
					alert.getLabels());
		}

	}

}
