package dev.oncallcopilot.alerts.incident;

import java.util.EnumSet;
import java.util.Set;

/**
 * Incident lifecycle. The allowed transitions are the core safety property of the system:
 * nothing reaches {@link #APPROVED} without passing through {@link #PENDING_APPROVAL} and a human decision.
 */
public enum IncidentStatus {

	/** Created by triage; agents haven't started. */
	OPEN,
	/** Investigator agent is gathering evidence. */
	INVESTIGATING,
	/** Root cause found and a guardrail-approved remediation is waiting for a human. */
	PENDING_APPROVAL,
	/** Analysis done but no safe automated action was found; a human must handle it. */
	NEEDS_HUMAN,
	/** Agent pipeline failed (e.g. all model calls timed out). Can be retried. */
	FAILED,
	APPROVED,
	REJECTED,
	RESOLVED;

	public Set<IncidentStatus> allowedNext() {
		return switch (this) {
			case OPEN -> EnumSet.of(INVESTIGATING, PENDING_APPROVAL, NEEDS_HUMAN, FAILED, RESOLVED);
			case INVESTIGATING -> EnumSet.of(PENDING_APPROVAL, NEEDS_HUMAN, FAILED);
			case FAILED -> EnumSet.of(INVESTIGATING, RESOLVED);
			case PENDING_APPROVAL -> EnumSet.of(APPROVED, REJECTED);
			case NEEDS_HUMAN, APPROVED, REJECTED -> EnumSet.of(RESOLVED);
			case RESOLVED -> EnumSet.noneOf(IncidentStatus.class);
		};
	}

	public boolean canTransitionTo(IncidentStatus next) {
		return allowedNext().contains(next);
	}

	/** Statuses that represent the end of the agent pipeline (a summary exists). */
	public static Set<IncidentStatus> analysisOutcomes() {
		return EnumSet.of(PENDING_APPROVAL, NEEDS_HUMAN, FAILED);
	}

}
