package dev.oncallcopilot.alerts.alert;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

@Entity
@Table(name = "alerts")
public class Alert {

	@Id
	private UUID id;

	@Column(nullable = false, length = 64)
	private String fingerprint;

	@Column(nullable = false, length = 64)
	private String source;

	@Column(nullable = false, length = 120)
	private String service;

	@Enumerated(EnumType.STRING)
	@Column(nullable = false, length = 16)
	private Severity severity;

	@Column(nullable = false, columnDefinition = "text")
	private String message;

	@Column(name = "alert_timestamp", nullable = false)
	private Instant timestamp;

	@Column(name = "received_at", nullable = false)
	private Instant receivedAt;

	@JdbcTypeCode(SqlTypes.JSON)
	@Column(nullable = false, columnDefinition = "jsonb")
	private Map<String, String> labels = new HashMap<>();

	@Column(name = "incident_id")
	private UUID incidentId;

	protected Alert() {
		// for JPA
	}

	public Alert(String source, String service, Severity severity, String message, Instant timestamp,
			Map<String, String> labels, Instant receivedAt) {
		this.id = UUID.randomUUID();
		this.source = source;
		this.service = service;
		this.severity = severity;
		this.message = message;
		this.timestamp = timestamp;
		this.labels = labels == null ? new HashMap<>() : new HashMap<>(labels);
		this.receivedAt = receivedAt;
		this.fingerprint = Fingerprints.of(source, service, message);
	}

	public void assignTo(UUID incidentId) {
		this.incidentId = incidentId;
	}

	public UUID getId() {
		return id;
	}

	public String getFingerprint() {
		return fingerprint;
	}

	public String getSource() {
		return source;
	}

	public String getService() {
		return service;
	}

	public Severity getSeverity() {
		return severity;
	}

	public String getMessage() {
		return message;
	}

	public Instant getTimestamp() {
		return timestamp;
	}

	public Instant getReceivedAt() {
		return receivedAt;
	}

	public Map<String, String> getLabels() {
		return labels;
	}

	public UUID getIncidentId() {
		return incidentId;
	}

}
