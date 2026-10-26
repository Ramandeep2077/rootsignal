package dev.oncallcopilot.alerts.incident;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.greaterThanOrEqualTo;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import dev.oncallcopilot.alerts.IntegrationTestSupport;
import java.time.Duration;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import tools.jackson.databind.JsonNode;

class IncidentLifecycleIT extends IntegrationTestSupport {

	private static final String ANALYSIS = """
			{"status":"PENDING_APPROVAL","title":"Checkout DB pool exhausted","severity":"CRITICAL",
			 "summary":"Connection pool on checkout is saturated after deploy v2.3.1",
			 "rootCause":{"category":"db_pool_exhaustion","hypothesis":"pool too small","confidence":0.86,
			              "evidence":[{"tool":"metrics","finding":"db_connections=50/50"}]},
			 "proposedAction":{"action":"scale_connection_pool","target":"checkout","risk_level":"low",
			                   "steps":["raise pool to 100"],"rollback_plan":"revert config","dry_run":true},
			 "reasoningTrace":[{"agent":"triage","step":"grouped 3 alerts"}],
			 "llmUsage":{"total_tokens":1234,"estimated_cost_usd":0.0}}
			""";

	private UUID createIncident(List<UUID> alertIds) throws Exception {
		String body = json.writeValueAsString(java.util.Map.of("title", "Checkout errors", "severity", "HIGH",
				"affectedServices", List.of("checkout"), "alertIds", alertIds));
		String response = mvc.perform(internal(post("/api/internal/incidents")).content(body))
				.andExpect(status().isCreated())
				.andExpect(jsonPath("$.status").value("OPEN"))
				.andReturn().getResponse().getContentAsString();
		return UUID.fromString(readJson(response).get("id").asString());
	}

	@Test
	void fullLifecycleFromAlertsToApprovedDecision() throws Exception {
		UUID a1 = postAlert("checkout", "HIGH", "5xx rate 12%");
		UUID a2 = postAlert("checkout", "HIGH", "5xx rate 14%");
		UUID a3 = postAlert("payments", "CRITICAL", "upstream checkout timeouts");

		UUID id = createIncident(List.of(a1, a2));
		mvc.perform(internal(post("/api/internal/incidents/{id}/alerts", id))
				.content(json.writeValueAsString(java.util.Map.of("alertIds", List.of(a3)))))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.severity").value("CRITICAL"))
				.andExpect(jsonPath("$.affectedServices.length()").value(2))
				.andExpect(jsonPath("$.alerts.length()").value(3));

		mvc.perform(internal(put("/api/internal/incidents/{id}/status", id)).content("{\"status\":\"INVESTIGATING\"}"))
				.andExpect(status().isOk());

		mvc.perform(internal(put("/api/internal/incidents/{id}/analysis", id)).content(ANALYSIS))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.status").value("PENDING_APPROVAL"))
				.andExpect(jsonPath("$.rootCause.confidence").value(0.86))
				.andExpect(jsonPath("$.proposedAction.action").value("scale_connection_pool"))
				.andExpect(jsonPath("$.timeToSummarySeconds").isNumber());

		mvc.perform(internal(post("/api/internal/incidents/{id}/notified", id)))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.notifiedAt").isNotEmpty());

		mvc.perform(get("/api/incidents").param("status", "PENDING_APPROVAL"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.items[?(@.id=='" + id + "')].alertCount").value(3))
				.andExpect(jsonPath("$.items[?(@.id=='" + id + "')].rootCauseCategory").value("db_pool_exhaustion"));

		mvc.perform(post("/api/incidents/{id}/approve", id).contentType(MediaType.APPLICATION_JSON)
				.content("{\"decidedBy\":\"alice\",\"comment\":\"go\"}"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.status").value("APPROVED"))
				.andExpect(jsonPath("$.decidedBy").value("alice"));

		JsonNode decision = awaitRecord("incidents.decisions", n -> id.toString().equals(n.path("incidentId").asString()),
				Duration.ofSeconds(20)).orElseThrow(() -> new AssertionError("decision not published"));
		assertThat(decision.get("decision").asString()).isEqualTo("APPROVED");
		assertThat(decision.get("proposedAction").get("action").asString()).isEqualTo("scale_connection_pool");

		// A decision is final: approving or rejecting again is a conflict.
		mvc.perform(post("/api/incidents/{id}/reject", id).contentType(MediaType.APPLICATION_JSON)
				.content("{\"decidedBy\":\"bob\"}"))
				.andExpect(status().isConflict())
				.andExpect(jsonPath("$.title").value("Invalid state transition"));

		mvc.perform(internal(put("/api/internal/incidents/{id}/execution", id))
				.content("{\"execution\":{\"dry_run\":true,\"result\":\"simulated\"}}"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.execution.dry_run").value(true));
	}

	@Test
	void cannotApproveBeforeAnalysis() throws Exception {
		UUID id = createIncident(List.of(postAlert("auth", "LOW", "login latency")));
		mvc.perform(post("/api/incidents/{id}/approve", id).contentType(MediaType.APPLICATION_JSON)
				.content("{\"decidedBy\":\"alice\"}"))
				.andExpect(status().isConflict());
	}

	@Test
	void pendingApprovalWithoutActionIsRejected() throws Exception {
		UUID id = createIncident(List.of(postAlert("auth", "LOW", "login errors")));
		mvc.perform(internal(put("/api/internal/incidents/{id}/analysis", id))
				.content("{\"status\":\"PENDING_APPROVAL\",\"summary\":\"s\"}"))
				.andExpect(status().isBadRequest());
	}

	@Test
	void alertCannotJoinTwoIncidents() throws Exception {
		UUID alert = postAlert("auth", "LOW", "token errors");
		createIncident(List.of(alert));
		String body = json.writeValueAsString(java.util.Map.of("title", "dup", "severity", "LOW",
				"affectedServices", List.of("auth"), "alertIds", List.of(alert)));
		mvc.perform(internal(post("/api/internal/incidents")).content(body)).andExpect(status().isConflict());
	}

	@Test
	void unknownAlertIdsAreRejected() throws Exception {
		String body = json.writeValueAsString(java.util.Map.of("title", "t", "severity", "LOW",
				"affectedServices", List.of("auth"), "alertIds", List.of(UUID.randomUUID())));
		mvc.perform(internal(post("/api/internal/incidents")).content(body)).andExpect(status().isBadRequest());
	}

	@Test
	void internalApiRequiresToken() throws Exception {
		mvc.perform(post("/api/internal/incidents").contentType(MediaType.APPLICATION_JSON).content("{}"))
				.andExpect(status().isUnauthorized());
		mvc.perform(post("/api/internal/incidents").header("X-Internal-Token", "wrong")
				.contentType(MediaType.APPLICATION_JSON).content("{}"))
				.andExpect(status().isUnauthorized());
	}

	@Test
	void unknownIncidentIs404() throws Exception {
		mvc.perform(get("/api/incidents/{id}", UUID.randomUUID()))
				.andExpect(status().isNotFound())
				.andExpect(jsonPath("$.title").value("Not found"));
	}

	@Test
	void metricsSummaryReflectsData() throws Exception {
		createIncident(List.of(postAlert("dns", "HIGH", "nxdomain"), postAlert("dns", "HIGH", "nxdomain")));
		mvc.perform(get("/api/metrics/summary"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.totalIncidents").value(greaterThanOrEqualTo(1)))
				.andExpect(jsonPath("$.groupedAlerts").value(greaterThanOrEqualTo(2)))
				.andExpect(jsonPath("$.noiseReductionPercent").isNumber())
				.andExpect(jsonPath("$.avgSecondsToNotification").hasJsonPath());
	}

}
