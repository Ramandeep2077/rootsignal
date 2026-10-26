package dev.oncallcopilot.alerts.alert;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import dev.oncallcopilot.alerts.IntegrationTestSupport;
import java.time.Duration;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import tools.jackson.databind.JsonNode;

class AlertIngestionIT extends IntegrationTestSupport {

	@Autowired
	AlertRepository alertRepository;

	@Test
	void alertIsStoredAndPublishedToKafka() throws Exception {
		UUID id = postAlert("checkout", "CRITICAL", "DB pool exhausted: 50/50 in use");

		Alert stored = alertRepository.findById(id).orElseThrow();
		assertThat(stored.getService()).isEqualTo("checkout");
		assertThat(stored.getLabels()).containsEntry("run", "it");

		JsonNode event = awaitRecord("alerts.raw", n -> id.toString().equals(n.path("id").asString()),
				Duration.ofSeconds(20)).orElseThrow(() -> new AssertionError("alert not published to alerts.raw"));
		assertThat(event.get("service").asString()).isEqualTo("checkout");
		assertThat(event.get("severity").asString()).isEqualTo("CRITICAL");
		assertThat(event.get("fingerprint").asString()).isEqualTo(stored.getFingerprint());
	}

	@Test
	void batchIngestStoresAllAlerts() throws Exception {
		String alert = """
				{"source":"test","service":"inventory","severity":"MEDIUM","message":"lag %d","timestamp":"2026-01-01T00:00:00Z"}""";
		String body = "{\"alerts\":[" + alert.formatted(1) + "," + alert.formatted(2) + "," + alert.formatted(3) + "]}";

		mvc.perform(post("/api/alerts/batch").contentType(MediaType.APPLICATION_JSON).content(body))
				.andExpect(status().isAccepted())
				.andExpect(jsonPath("$.accepted").value(3));

		mvc.perform(get("/api/alerts").param("service", "inventory"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.totalItems").value(org.hamcrest.Matchers.greaterThanOrEqualTo(3)));
	}

	@Test
	void openApiDocsAreServed() throws Exception {
		mvc.perform(get("/v3/api-docs"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.paths['/api/alerts']").exists())
				.andExpect(jsonPath("$.paths['/api/incidents/{id}/approve']").exists());
	}

}
