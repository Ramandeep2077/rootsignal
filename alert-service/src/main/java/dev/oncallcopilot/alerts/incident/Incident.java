package dev.oncallcopilot.alerts.incident;

import dev.oncallcopilot.alerts.alert.Severity;
import dev.oncallcopilot.alerts.error.InvalidStateTransitionException;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.Version;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

/**
 * An incident groups related alerts and carries the agents' analysis. All state changes go through
 * methods that enforce {@link IncidentStatus#canTransitionTo}, so invalid lifecycles can't be persisted.
 */
@Entity
@Table(name = "incidents")
public class Incident {

	@Id
	private UUID id;

	@Column(nullable = false, length = 300)
	private String title;

	@Enumerated(EnumType.STRING)
	@Column(nullable = false, length = 32)
	private IncidentStatus status;

	@Enumerated(EnumType.STRING)
	@Column(nullable = false, length = 16)
	private Severity severity;

	@JdbcTypeCode(SqlTypes.JSON)
	@Column(name = "affected_services", nullable = false, columnDefinition = "jsonb")
	private List<String> affectedServices = new ArrayList<>();

	@Column(columnDefinition = "text")
	private String summary;

	@JdbcTypeCode(SqlTypes.JSON)
	@Column(name = "root_cause", columnDefinition = "jsonb")
	private Map<String, Object> rootCause;

	@JdbcTypeCode(SqlTypes.JSON)
	@Column(name = "proposed_action", columnDefinition = "jsonb")
	private Map<String, Object> proposedAction;

	@JdbcTypeCode(SqlTypes.JSON)
	@Column(name = "reasoning_trace", columnDefinition = "jsonb")
	private List<Map<String, Object>> reasoningTrace;

	@JdbcTypeCode(SqlTypes.JSON)
	@Column(name = "llm_usage", columnDefinition = "jsonb")
	private Map<String, Object> llmUsage;

	@JdbcTypeCode(SqlTypes.JSON)
	@Column(columnDefinition = "jsonb")
	private Map<String, Object> execution;

	@Column(name = "first_alert_at", nullable = false)
	private Instant firstAlertAt;

	@Column(name = "summarized_at")
	private Instant summarizedAt;

	@Column(name = "notified_at")
	private Instant notifiedAt;

	@Column(name = "decided_at")
	private Instant decidedAt;

	@Column(name = "decided_by", length = 120)
	private String decidedBy;

	@Column(name = "decision_comment", columnDefinition = "text")
	private String decisionComment;

	@Column(name = "created_at", nullable = false)
	private Instant createdAt;

	@Column(name = "updated_at", nullable = false)
	private Instant updatedAt;

	@Version
	private long version;

	protected Incident() {
		// for JPA
	}

	public Incident(String title, Severity severity, Collection<String> affectedServices, Instant firstAlertAt,
			Instant now) {
		this.id = UUID.randomUUID();
		this.title = title;
		this.status = IncidentStatus.OPEN;
		this.severity = severity;
		this.affectedServices = new ArrayList<>(new LinkedHashSet<>(affectedServices));
		this.firstAlertAt = firstAlertAt;
		this.createdAt = now;
		this.updatedAt = now;
	}

	/** Widen the incident when triage attaches more alerts: union of services, highest severity, earliest alert. */
	public void absorb(Collection<String> services, Severity alertSeverity, Instant earliestAlert, Instant now) {
		Set<String> merged = new LinkedHashSet<>(affectedServices);
		merged.addAll(services);
		this.affectedServices = new ArrayList<>(merged);
		if (alertSeverity != null && alertSeverity.isMoreSevereThan(severity)) {
			this.severity = alertSeverity;
		}
		if (earliestAlert != null && earliestAlert.isBefore(firstAlertAt)) {
			this.firstAlertAt = earliestAlert;
		}
		this.updatedAt = now;
	}

	public void transitionTo(IncidentStatus next, Instant now) {
		if (!status.canTransitionTo(next)) {
			throw new InvalidStateTransitionException(
					"Incident %s cannot move from %s to %s".formatted(id, status, next));
		}
		this.status = next;
		this.updatedAt = now;
	}

	public void recordAnalysis(IncidentStatus outcome, String newTitle, Severity newSeverity, String summary,
			Map<String, Object> rootCause, Map<String, Object> proposedAction, List<Map<String, Object>> reasoningTrace,
			Map<String, Object> llmUsage, Instant now) {
		if (!IncidentStatus.analysisOutcomes().contains(outcome)) {
			throw new IllegalArgumentException("Analysis outcome must be one of " + IncidentStatus.analysisOutcomes());
		}
		if (outcome == IncidentStatus.PENDING_APPROVAL && (proposedAction == null || proposedAction.isEmpty())) {
			throw new IllegalArgumentException("PENDING_APPROVAL requires a proposedAction");
		}
		transitionTo(outcome, now);
		if (newTitle != null && !newTitle.isBlank()) {
			this.title = newTitle;
		}
		if (newSeverity != null) {
			this.severity = newSeverity;
		}
		this.summary = summary;
		this.rootCause = rootCause;
		this.proposedAction = proposedAction;
		this.reasoningTrace = reasoningTrace;
		this.llmUsage = llmUsage;
		this.summarizedAt = now;
	}

	public void decide(boolean approved, String decidedBy, String comment, Instant now) {
		transitionTo(approved ? IncidentStatus.APPROVED : IncidentStatus.REJECTED, now);
		this.decidedBy = decidedBy;
		this.decisionComment = comment;
		this.decidedAt = now;
	}

	public void markNotified(Instant now) {
		this.notifiedAt = now;
		this.updatedAt = now;
	}

	public void recordExecution(Map<String, Object> execution, Instant now) {
		if (status != IncidentStatus.APPROVED && status != IncidentStatus.RESOLVED) {
			throw new InvalidStateTransitionException("Only approved incidents can record an execution; status is " + status);
		}
		this.execution = execution;
		this.updatedAt = now;
	}

	public UUID getId() {
		return id;
	}

	public String getTitle() {
		return title;
	}

	public IncidentStatus getStatus() {
		return status;
	}

	public Severity getSeverity() {
		return severity;
	}

	public List<String> getAffectedServices() {
		return affectedServices;
	}

	public String getSummary() {
		return summary;
	}

	public Map<String, Object> getRootCause() {
		return rootCause;
	}

	public Map<String, Object> getProposedAction() {
		return proposedAction;
	}

	public List<Map<String, Object>> getReasoningTrace() {
		return reasoningTrace;
	}

	public Map<String, Object> getLlmUsage() {
		return llmUsage;
	}

	public Map<String, Object> getExecution() {
		return execution;
	}

	public Instant getFirstAlertAt() {
		return firstAlertAt;
	}

	public Instant getSummarizedAt() {
		return summarizedAt;
	}

	public Instant getNotifiedAt() {
		return notifiedAt;
	}

	public Instant getDecidedAt() {
		return decidedAt;
	}

	public String getDecidedBy() {
		return decidedBy;
	}

	public String getDecisionComment() {
		return decisionComment;
	}

	public Instant getCreatedAt() {
		return createdAt;
	}

	public Instant getUpdatedAt() {
		return updatedAt;
	}

}
