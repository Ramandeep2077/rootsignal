package dev.oncallcopilot.alerts.incident;

import dev.oncallcopilot.alerts.incident.IncidentDtos.AnalysisRequest;
import dev.oncallcopilot.alerts.incident.IncidentDtos.AttachAlertsRequest;
import dev.oncallcopilot.alerts.incident.IncidentDtos.CreateIncidentRequest;
import dev.oncallcopilot.alerts.incident.IncidentDtos.ExecutionRequest;
import dev.oncallcopilot.alerts.incident.IncidentDtos.IncidentDetail;
import dev.oncallcopilot.alerts.incident.IncidentDtos.StatusRequest;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import java.net.URI;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Service-to-service API used by the agent service. Requires the {@code X-Internal-Token} header. */
@Tag(name = "Internal", description = "Agent service write-back (requires X-Internal-Token)")
@SecurityRequirement(name = "internalToken")
@RestController
@RequestMapping("/api/internal/incidents")
public class InternalIncidentController {

	private final IncidentService incidentService;

	public InternalIncidentController(IncidentService incidentService) {
		this.incidentService = incidentService;
	}

	@Operation(summary = "Create an incident from a group of alerts (triage output)")
	@PostMapping
	public ResponseEntity<IncidentDetail> create(@Valid @RequestBody CreateIncidentRequest request) {
		IncidentDetail incident = incidentService.create(request);
		return ResponseEntity.created(URI.create("/api/incidents/" + incident.id())).body(incident);
	}

	@Operation(summary = "Attach more alerts to an existing incident")
	@PostMapping("/{id}/alerts")
	public IncidentDetail attach(@PathVariable UUID id, @Valid @RequestBody AttachAlertsRequest request) {
		return incidentService.attachAlerts(id, request.alertIds());
	}

	@Operation(summary = "Move the incident to a new status (e.g. INVESTIGATING)")
	@PutMapping("/{id}/status")
	public IncidentDetail status(@PathVariable UUID id, @Valid @RequestBody StatusRequest request) {
		return incidentService.updateStatus(id, request.status());
	}

	@Operation(summary = "Store the agents' analysis: summary, root cause, evidence, proposed action, trace, usage")
	@PutMapping("/{id}/analysis")
	public IncidentDetail analysis(@PathVariable UUID id, @Valid @RequestBody AnalysisRequest request) {
		return incidentService.recordAnalysis(id, request);
	}

	@Operation(summary = "Record that the summary notification was sent")
	@PostMapping("/{id}/notified")
	public IncidentDetail notified(@PathVariable UUID id) {
		return incidentService.markNotified(id);
	}

	@Operation(summary = "Record the (dry-run) execution result of an approved action")
	@PutMapping("/{id}/execution")
	public IncidentDetail execution(@PathVariable UUID id, @Valid @RequestBody ExecutionRequest request) {
		return incidentService.recordExecution(id, request.execution());
	}

}
