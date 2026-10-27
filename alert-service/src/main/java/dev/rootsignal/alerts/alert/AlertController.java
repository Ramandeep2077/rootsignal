package dev.rootsignal.alerts.alert;

import dev.rootsignal.alerts.alert.AlertDtos.AlertBatchRequest;
import dev.rootsignal.alerts.alert.AlertDtos.AlertBatchResponse;
import dev.rootsignal.alerts.alert.AlertDtos.AlertRequest;
import dev.rootsignal.alerts.alert.AlertDtos.AlertResponse;
import dev.rootsignal.alerts.config.PageResponse;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import java.net.URI;
import java.util.List;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "Alerts", description = "Webhook for monitoring tools")
@RestController
@RequestMapping("/api/alerts")
public class AlertController {

	private final AlertService alertService;

	public AlertController(AlertService alertService) {
		this.alertService = alertService;
	}

	@Operation(summary = "Ingest one alert", description = "Validates, stores and publishes the alert to Kafka topic alerts.raw")
	@PostMapping
	public ResponseEntity<AlertResponse> ingest(@Valid @RequestBody AlertRequest request) {
		Alert alert = alertService.ingest(request);
		return ResponseEntity.accepted()
				.location(URI.create("/api/alerts/" + alert.getId()))
				.body(AlertResponse.from(alert));
	}

	@Operation(summary = "Ingest up to 500 alerts in one request")
	@PostMapping("/batch")
	public ResponseEntity<AlertBatchResponse> ingestBatch(@Valid @RequestBody AlertBatchRequest request) {
		List<UUID> ids = alertService.ingestAll(request.alerts()).stream().map(Alert::getId).toList();
		return ResponseEntity.accepted().body(new AlertBatchResponse(ids.size(), ids));
	}

	@Operation(summary = "List alerts, newest first")
	@GetMapping
	public PageResponse<AlertResponse> list(@RequestParam(required = false) String service,
			@RequestParam(required = false) UUID incidentId,
			@RequestParam(defaultValue = "0") @Min(0) int page,
			@RequestParam(defaultValue = "50") @Min(1) @Max(500) int size) {
		return PageResponse.of(alertService.search(service, incidentId, page, size), AlertResponse::from);
	}

}
