package dev.oncallcopilot.alerts;

import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.context.annotation.Bean;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.redpanda.RedpandaContainer;
import org.testcontainers.utility.DockerImageName;

/**
 * Spins up the same Postgres (pgvector) and Redpanda images used by docker-compose,
 * so integration tests exercise the real infrastructure rather than mocks.
 */
@TestConfiguration(proxyBeanMethods = false)
public class TestcontainersConfiguration {

	static final String POSTGRES_IMAGE = "pgvector/pgvector:0.8.7-pg17-trixie";
	static final String REDPANDA_IMAGE = "redpandadata/redpanda:v26.2.6";

	@Bean
	@ServiceConnection
	RedpandaContainer redpandaContainer() {
		return new RedpandaContainer(DockerImageName.parse(REDPANDA_IMAGE));
	}

	@Bean
	@ServiceConnection
	PostgreSQLContainer postgresContainer() {
		return new PostgreSQLContainer(
				DockerImageName.parse(POSTGRES_IMAGE).asCompatibleSubstituteFor("postgres"));
	}

}
