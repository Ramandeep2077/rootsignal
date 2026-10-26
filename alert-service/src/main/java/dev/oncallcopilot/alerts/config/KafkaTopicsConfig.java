package dev.oncallcopilot.alerts.config;

import org.apache.kafka.clients.admin.NewTopic;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.config.TopicBuilder;

/** Declares the topics this service produces to; Spring's KafkaAdmin creates them if missing. */
@Configuration
public class KafkaTopicsConfig {

	private static final int PARTITIONS = 3;

	@Bean
	NewTopic alertsTopic(OncallProperties properties) {
		return TopicBuilder.name(properties.alertsTopic()).partitions(PARTITIONS).replicas(1).build();
	}

	@Bean
	NewTopic decisionsTopic(OncallProperties properties) {
		return TopicBuilder.name(properties.decisionsTopic()).partitions(PARTITIONS).replicas(1).build();
	}

}
