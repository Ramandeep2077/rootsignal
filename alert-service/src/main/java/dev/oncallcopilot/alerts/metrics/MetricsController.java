package dev.oncallcopilot.alerts.metrics;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Aggregate operational metrics for the dashboard. Computed in SQL so it stays cheap as data grows. */
@Tag(name = "Metrics")
@RestController
@RequestMapping("/api/metrics")
public class MetricsController {

	public record MetricsSummary(long totalAlerts, long groupedAlerts, long totalIncidents,
			Double noiseReductionPercent, Double avgSecondsToSummary, Double p50SecondsToSummary,
			Double p95SecondsToSummary, Double avgSecondsToNotification, Double avgCostUsd, Double avgTotalTokens,
			Map<String, Long> incidentsByStatus) {
	}

	private final JdbcClient jdbc;

	public MetricsController(JdbcClient jdbc) {
		this.jdbc = jdbc;
	}

	@Operation(summary = "Alert-to-incident reduction, time to summary and cost per incident")
	@GetMapping("/summary")
	@Transactional(readOnly = true)
	public MetricsSummary summary() {
		Map<String, Object> row = jdbc.sql("""
				with tts as (
				  select extract(epoch from summarized_at - first_alert_at) as seconds
				  from incidents where summarized_at is not null
				)
				select
				  (select count(*) from alerts) as total_alerts,
				  (select count(*) from alerts where incident_id is not null) as grouped_alerts,
				  (select count(*) from incidents) as total_incidents,
				  (select avg(seconds) from tts) as avg_tts,
				  (select percentile_cont(0.5) within group (order by seconds) from tts) as p50_tts,
				  (select percentile_cont(0.95) within group (order by seconds) from tts) as p95_tts,
				  (select avg(extract(epoch from notified_at - first_alert_at)) from incidents
				     where notified_at is not null) as avg_ttn,
				  (select avg((llm_usage ->> 'estimated_cost_usd')::numeric) from incidents
				     where llm_usage ->> 'estimated_cost_usd' is not null) as avg_cost,
				  (select avg((llm_usage ->> 'total_tokens')::numeric) from incidents
				     where llm_usage ->> 'total_tokens' is not null) as avg_tokens
				""").query().singleRow();

		Map<String, Long> byStatus = new LinkedHashMap<>();
		jdbc.sql("select status, count(*) as n from incidents group by status order by status")
				.query((rs, i) -> Map.entry(rs.getString("status"), rs.getLong("n")))
				.list()
				.forEach(e -> byStatus.put(e.getKey(), e.getValue()));

		long grouped = toLong(row.get("grouped_alerts"));
		long incidents = toLong(row.get("total_incidents"));
		Double reduction = grouped == 0 ? null : 100.0 * (1.0 - (double) incidents / grouped);
		return new MetricsSummary(toLong(row.get("total_alerts")), grouped, incidents, reduction,
				toDouble(row.get("avg_tts")), toDouble(row.get("p50_tts")), toDouble(row.get("p95_tts")),
				toDouble(row.get("avg_ttn")),
				toDouble(row.get("avg_cost")), toDouble(row.get("avg_tokens")), byStatus);
	}

	private static long toLong(Object value) {
		return value == null ? 0 : ((Number) value).longValue();
	}

	private static Double toDouble(Object value) {
		return value == null ? null : ((Number) value).doubleValue();
	}

}
