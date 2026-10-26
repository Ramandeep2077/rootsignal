package dev.oncallcopilot.alerts.config;

import jakarta.validation.constraints.NotBlank;
import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

/** Application settings bound from the {@code oncall.*} namespace (env vars like {@code ONCALL_ALERTS_TOPIC}). */
@Validated
@ConfigurationProperties(prefix = "oncall")
public record OncallProperties(
		@NotBlank String alertsTopic,
		@NotBlank String decisionsTopic,
		@NotBlank String internalApiToken,
		List<String> corsAllowedOrigins) {
}
