package dev.oncallcopilot.alerts.incident;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import dev.oncallcopilot.alerts.alert.Severity;
import dev.oncallcopilot.alerts.error.InvalidStateTransitionException;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;

class IncidentTest {

	private static final Instant T0 = Instant.parse("2026-01-01T00:00:00Z");
	private static final Map<String, Object> ACTION = Map.of("action", "restart_service", "target", "checkout");

	private static Incident newIncident() {
		return new Incident("Checkout errors", Severity.HIGH, List.of("checkout"), T0, T0);
	}

	@Test
	void newIncidentStartsOpen() {
		assertThat(newIncident().getStatus()).isEqualTo(IncidentStatus.OPEN);
	}

	@Test
	void cannotApproveWithoutPendingApproval() {
		Incident incident = newIncident();
		assertThatThrownBy(() -> incident.decide(true, "alice", null, T0))
				.isInstanceOf(InvalidStateTransitionException.class);
	}

	@Test
	void pendingApprovalRequiresAProposedAction() {
		Incident incident = newIncident();
		assertThatThrownBy(() -> incident.recordAnalysis(IncidentStatus.PENDING_APPROVAL, null, null, "summary",
				Map.of(), null, List.of(), Map.of(), T0)).isInstanceOf(IllegalArgumentException.class);
	}

	@Test
	void analysisThenApprovalRecordsDecision() {
		Incident incident = newIncident();
		incident.transitionTo(IncidentStatus.INVESTIGATING, T0);
		Instant summarized = T0.plusSeconds(42);
		incident.recordAnalysis(IncidentStatus.PENDING_APPROVAL, "DB pool exhausted", Severity.CRITICAL, "summary",
				Map.of("category", "db_pool_exhaustion"), ACTION, List.of(), Map.of("total_tokens", 100), summarized);

		assertThat(incident.getStatus()).isEqualTo(IncidentStatus.PENDING_APPROVAL);
		assertThat(incident.getTitle()).isEqualTo("DB pool exhausted");
		assertThat(incident.getSeverity()).isEqualTo(Severity.CRITICAL);
		assertThat(IncidentDtos.timeToSummary(incident)).isEqualTo(42.0);

		incident.decide(true, "alice", "looks right", T0.plusSeconds(60));
		assertThat(incident.getStatus()).isEqualTo(IncidentStatus.APPROVED);
		assertThat(incident.getDecidedBy()).isEqualTo("alice");

		assertThatThrownBy(() -> incident.decide(false, "bob", null, T0.plusSeconds(61)))
				.as("a decision is final")
				.isInstanceOf(InvalidStateTransitionException.class);
	}

	@Test
	void absorbWidensServicesSeverityAndStartTime() {
		Incident incident = newIncident();
		incident.absorb(List.of("payments", "checkout"), Severity.CRITICAL, T0.minusSeconds(5), T0);
		assertThat(incident.getAffectedServices()).containsExactly("checkout", "payments");
		assertThat(incident.getSeverity()).isEqualTo(Severity.CRITICAL);
		assertThat(incident.getFirstAlertAt()).isEqualTo(T0.minusSeconds(5));

		incident.absorb(List.of(), Severity.LOW, T0.plusSeconds(5), T0);
		assertThat(incident.getSeverity()).as("never downgraded").isEqualTo(Severity.CRITICAL);
	}

	@Test
	void executionOnlyAfterApproval() {
		Incident incident = newIncident();
		assertThatThrownBy(() -> incident.recordExecution(Map.of("dry_run", true), T0))
				.isInstanceOf(InvalidStateTransitionException.class);
	}

	/** Safety property: the only path into APPROVED is from PENDING_APPROVAL. */
	@ParameterizedTest
	@EnumSource(IncidentStatus.class)
	void onlyPendingApprovalCanBecomeApproved(IncidentStatus from) {
		assertThat(from.canTransitionTo(IncidentStatus.APPROVED)).isEqualTo(from == IncidentStatus.PENDING_APPROVAL);
	}

}
