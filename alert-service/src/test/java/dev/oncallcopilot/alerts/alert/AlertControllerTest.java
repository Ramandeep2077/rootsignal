package dev.oncallcopilot.alerts.alert;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import dev.oncallcopilot.alerts.config.OncallProperties;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

/** Web-layer slice test: request validation and error mapping, with the service mocked out. */
@WebMvcTest(AlertController.class)
@Import(AlertControllerTest.Props.class)
class AlertControllerTest {

	@TestConfiguration
	@EnableConfigurationProperties(OncallProperties.class)
	static class Props {
	}

	@Autowired
	MockMvc mvc;

	@MockitoBean
	AlertService alertService;

	@Test
	void acceptsValidAlert() throws Exception {
		Alert saved = new Alert("prometheus", "checkout", Severity.HIGH, "high latency",
				Instant.parse("2026-01-01T00:00:00Z"), Map.of("env", "prod"), Instant.parse("2026-01-01T00:00:01Z"));
		given(alertService.ingest(any())).willReturn(saved);

		mvc.perform(post("/api/alerts").contentType(MediaType.APPLICATION_JSON).content("""
				{"source":"prometheus","service":"checkout","severity":"high","message":"high latency",
				 "timestamp":"2026-01-01T00:00:00Z","labels":{"env":"prod"}}
				"""))
				.andExpect(status().isAccepted())
				.andExpect(header().string("Location", "/api/alerts/" + saved.getId()))
				.andExpect(jsonPath("$.severity").value("HIGH"))
				.andExpect(jsonPath("$.fingerprint").isNotEmpty());
	}

	@Test
	void rejectsMissingFieldsWithFieldErrors() throws Exception {
		mvc.perform(post("/api/alerts").contentType(MediaType.APPLICATION_JSON).content("""
				{"source":"prometheus","severity":"HIGH","timestamp":"2026-01-01T00:00:00Z"}
				"""))
				.andExpect(status().isBadRequest())
				.andExpect(jsonPath("$.title").value("Validation failed"))
				.andExpect(jsonPath("$.errors.service").exists())
				.andExpect(jsonPath("$.errors.message").exists());
		verifyNoInteractions(alertService);
	}

	@Test
	void rejectsUnknownSeverity() throws Exception {
		mvc.perform(post("/api/alerts").contentType(MediaType.APPLICATION_JSON).content("""
				{"source":"p","service":"checkout","severity":"apocalyptic","message":"m","timestamp":"2026-01-01T00:00:00Z"}
				"""))
				.andExpect(status().isBadRequest())
				.andExpect(jsonPath("$.detail").value(org.hamcrest.Matchers.containsString("Unknown severity")));
	}

	@Test
	void rejectsInvalidServiceName() throws Exception {
		mvc.perform(post("/api/alerts").contentType(MediaType.APPLICATION_JSON).content("""
				{"source":"p","service":"Checkout Service!","severity":"LOW","message":"m","timestamp":"2026-01-01T00:00:00Z"}
				"""))
				.andExpect(status().isBadRequest())
				.andExpect(jsonPath("$.errors.service").exists());
	}

	@Test
	void rejectsMalformedJson() throws Exception {
		mvc.perform(post("/api/alerts").contentType(MediaType.APPLICATION_JSON).content("{not json"))
				.andExpect(status().isBadRequest());
	}

	@Test
	void rejectsEmptyBatch() throws Exception {
		mvc.perform(post("/api/alerts/batch").contentType(MediaType.APPLICATION_JSON).content("{\"alerts\":[]}"))
				.andExpect(status().isBadRequest());
	}

}
