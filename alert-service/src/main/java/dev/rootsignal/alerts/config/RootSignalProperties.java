package dev.rootsignal.alerts.config;

import jakarta.validation.constraints.NotBlank;
import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

/** Application settings bound from the {@code rootsignal.*} namespace (env vars like {@code ROOTSIGNAL_ALERTS_TOPIC}). */
@Validated
@ConfigurationProperties(prefix = "rootsignal")
public record RootSignalProperties(
		@NotBlank String alertsTopic,
		@NotBlank String decisionsTopic,
		@NotBlank String internalApiToken,
		List<String> corsAllowedOrigins) {
}
