package dev.rootsignal.alerts;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import dev.rootsignal.alerts.config.InternalApiTokenInterceptor;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Properties;
import java.util.UUID;
import java.util.function.Predicate;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.kafka.autoconfigure.KafkaConnectionDetails;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * Base for full-stack tests: real Postgres (pgvector) and Redpanda via Testcontainers.
 * The Spring context and containers are shared by every subclass thanks to context caching.
 */
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration.class)
public abstract class IntegrationTestSupport {

	protected static final String TOKEN = "change-me-local-only";

	@Autowired
	protected MockMvc mvc;

	@Autowired
	protected JsonMapper json;

	@Autowired
	protected KafkaConnectionDetails kafkaConnection;

	protected UUID postAlert(String service, String severity, String message) throws Exception {
		String body = json.writeValueAsString(Map.of("source", "test", "service", service, "severity", severity,
				"message", message, "timestamp", Instant.now().toString(), "labels", Map.of("run", "it")));
		String response = mvc.perform(post("/api/alerts").contentType(MediaType.APPLICATION_JSON).content(body))
				.andExpect(status().isAccepted())
				.andReturn().getResponse().getContentAsString();
		return UUID.fromString(json.readTree(response).get("id").asString());
	}

	protected MockHttpServletRequestBuilder internal(MockHttpServletRequestBuilder request) {
		return request.header(InternalApiTokenInterceptor.HEADER, TOKEN).contentType(MediaType.APPLICATION_JSON);
	}

	protected JsonNode readJson(String content) {
		return json.readTree(content);
	}

	/** Polls a topic from the beginning until a record matches, or the timeout elapses. */
	protected Optional<JsonNode> awaitRecord(String topic, Predicate<JsonNode> matcher, Duration timeout) {
		Properties props = new Properties();
		props.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, String.join(",", kafkaConnection.getBootstrapServers()));
		props.put(ConsumerConfig.GROUP_ID_CONFIG, "it-" + UUID.randomUUID());
		props.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");
		props.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName());
		props.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName());
		try (KafkaConsumer<String, String> consumer = new KafkaConsumer<>(props)) {
			consumer.subscribe(List.of(topic));
			Instant deadline = Instant.now().plus(timeout);
			while (Instant.now().isBefore(deadline)) {
				for (ConsumerRecord<String, String> record : consumer.poll(Duration.ofMillis(500))) {
					JsonNode node = json.readTree(record.value());
					if (matcher.test(node)) {
						return Optional.of(node);
					}
				}
			}
		}
		return Optional.empty();
	}

}
