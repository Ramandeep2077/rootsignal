package dev.rootsignal.alerts.config;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Component;
import tools.jackson.databind.json.JsonMapper;

/**
 * Serialises events to JSON with the application's Jackson mapper and sends them as plain strings,
 * so consumers in any language (the Python agent service) only need a JSON parser.
 */
@Component
public class KafkaEventPublisher {

	private static final Logger log = LoggerFactory.getLogger(KafkaEventPublisher.class);

	private final KafkaTemplate<String, String> kafkaTemplate;
	private final JsonMapper jsonMapper;

	public KafkaEventPublisher(KafkaTemplate<String, String> kafkaTemplate, JsonMapper jsonMapper) {
		this.kafkaTemplate = kafkaTemplate;
		this.jsonMapper = jsonMapper;
	}

	public void publish(String topic, String key, Object event) {
		String payload = jsonMapper.writeValueAsString(event);
		kafkaTemplate.send(topic, key, payload).whenComplete((result, ex) -> {
			if (ex != null) {
				// The row is already committed; a production system would use a transactional outbox to retry.
				log.error("Failed to publish event to {} (key={})", topic, key, ex);
			}
		});
	}

}
