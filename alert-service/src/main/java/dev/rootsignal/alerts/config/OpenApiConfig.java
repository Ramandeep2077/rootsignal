package dev.rootsignal.alerts.config;

import io.swagger.v3.oas.models.Components;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.info.License;
import io.swagger.v3.oas.models.security.SecurityScheme;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class OpenApiConfig {

	@Bean
	OpenAPI rootSignalOpenApi() {
		return new OpenAPI().info(new Info()
				.title("rootsignal alert service")
				.description("Alert ingestion webhook, incidents API and human approval of agent-proposed remediations.")
				.version("v1")
				.license(new License().name("MIT")))
				.components(new Components().addSecuritySchemes("internalToken", new SecurityScheme()
						.type(SecurityScheme.Type.APIKEY)
						.in(SecurityScheme.In.HEADER)
						.name(InternalApiTokenInterceptor.HEADER)));
	}

}
