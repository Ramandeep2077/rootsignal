import random
from datetime import UTC, datetime, timedelta

from oncall_sim.alerting import AlertEngine, top_error
from oncall_sim.engine import PROFILES, baseline_metrics
from oncall_sim.model import LogLine

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _metrics(**overrides):
    rng = random.Random(0)
    current = {name: baseline_metrics(profile, rng) for name, profile in PROFILES.items()}
    current["checkout"].update(overrides)
    return current


def test_healthy_baseline_fires_nothing():
    engine = AlertEngine(PROFILES)
    logs = {s: [] for s in PROFILES}
    for tick in range(20):
        assert engine.evaluate(T0 + timedelta(seconds=30 * tick), _metrics(), logs) == []


def test_rule_waits_for_duration_then_repeats():
    engine = AlertEngine(PROFILES)
    logs = {s: [] for s in PROFILES}
    fired_at = []
    for tick in range(8):
        alerts = engine.evaluate(T0 + timedelta(seconds=30 * tick), _metrics(error_rate=0.12), logs)
        if any(a.labels["alertname"] == "HighErrorRate" and a.service == "checkout" for a in alerts):
            fired_at.append(tick)
    # for_ticks=2 -> first fire on the 2nd tick (index 1), then every 3 ticks.
    assert fired_at == [1, 4, 7]


def test_top_error_groups_messages_that_differ_only_in_numbers():
    lines = [
        LogLine(T0, "checkout", "ERROR", "pool timeout waiting=31"),
        LogLine(T0, "checkout", "ERROR", "pool timeout waiting=45"),
        LogLine(T0, "checkout", "ERROR", "other failure"),
        LogLine(T0, "checkout", "INFO", "fine"),
    ]
    message, count = top_error(lines)
    assert message.startswith("pool timeout") and count == 2
