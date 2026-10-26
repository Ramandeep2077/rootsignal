package dev.oncallcopilot.alerts.incident;

import dev.oncallcopilot.alerts.config.PageResponse;
import dev.oncallcopilot.alerts.incident.IncidentDtos.DecisionRequest;
import dev.oncallcopilot.alerts.incident.IncidentDtos.IncidentDetail;
import dev.oncallcopilot.alerts.incident.IncidentDtos.IncidentSummary;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import java.util.UUID;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "Incidents", description = "Grouped incidents and human approval of proposed remediations")
@RestController
@RequestMapping("/api/incidents")
public class IncidentController {

	private final IncidentService incidentService;

	public IncidentController(IncidentService incidentService) {
		this.incidentService = incidentService;
	}

	@Operation(summary = "List incidents, newest first")
	@GetMapping
	public PageResponse<IncidentSummary> list(@RequestParam(required = false) IncidentStatus status,
			@RequestParam(defaultValue = "0") @Min(0) int page,
			@RequestParam(defaultValue = "20") @Min(1) @Max(200) int size) {
		return incidentService.list(status, page, size);
	}

	@Operation(summary = "Incident detail with alert timeline, reasoning trace, evidence and proposed action")
	@GetMapping("/{id}")
	public IncidentDetail get(@PathVariable UUID id) {
		return incidentService.get(id);
	}

	@Operation(summary = "Approve the proposed action", description = "Only valid in PENDING_APPROVAL. Publishes to incidents.decisions.")
	@PostMapping("/{id}/approve")
	public IncidentDetail approve(@PathVariable UUID id, @Valid @RequestBody DecisionRequest request) {
		return incidentService.approve(id, request);
	}

	@Operation(summary = "Reject the proposed action", description = "Only valid in PENDING_APPROVAL. Publishes to incidents.decisions.")
	@PostMapping("/{id}/reject")
	public IncidentDetail reject(@PathVariable UUID id, @Valid @RequestBody DecisionRequest request) {
		return incidentService.reject(id, request);
	}

}
