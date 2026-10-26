from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest

from oncall_common.taxonomy import SERVICES, RootCauseCategory
from oncall_sim.engine import simulate
from oncall_sim.scenarios import SCENARIOS, get_scenario

END = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
ALL = sorted(SCENARIOS)


def test_at_least_twelve_scenarios_cover_every_category():
    assert len(SCENARIOS) >= 12
    covered = {s.ground_truth.category for s in SCENARIOS.values()}
    assert covered == set(RootCauseCategory) - {RootCauseCategory.UNKNOWN}


@pytest.mark.parametrize("name", ALL)
def test_scenario_is_deterministic(name):
    a = simulate(get_scenario(name), seed=3, end=END)
    b = simulate(get_scenario(name), seed=3, end=END)
    assert [(x.ts, x.service, x.message) for x in a.alerts] == [
        (x.ts, x.service, x.message) for x in b.alerts
    ]
    assert [x.message for x in a.logs] == [x.message for x in b.logs]


@pytest.mark.parametrize("name", ALL)
def test_scenario_produces_a_noisy_duplicated_storm(name):
    out = simulate(get_scenario(name), seed=1, end=END)
    real = [a for a in out.alerts if not a.is_noise]
    assert len(real) >= 15, "an incident should be an alert storm"
    assert len({a.service for a in real}) >= 2, "symptoms should spread beyond one service"
    repeats = Counter((a.labels["alertname"], a.service) for a in real)
    assert max(repeats.values()) >= 3, "alert rules should re-fire, producing duplicates"
    assert sum(a.is_noise for a in out.alerts) == 1, "one unrelated background alert"
    assert all(a.service in SERVICES for a in out.alerts)


@pytest.mark.parametrize("name", ALL)
def test_ground_truth_evidence_is_discoverable_in_telemetry(name):
    out = simulate(get_scenario(name), seed=1, end=END)
    text = "\n".join(line.message for line in out.logs)
    for keyword in out.ground_truth.evidence_keywords:
        assert keyword in text, f"{name}: evidence '{keyword}' missing from logs"


@pytest.mark.parametrize("name", ALL)
def test_telemetry_stays_inside_the_window(name):
    out = simulate(get_scenario(name), seed=1, end=END)
    assert out.end - out.start == timedelta(minutes=30)
    assert all(out.start <= line.ts <= out.end for line in out.logs)
    assert all(out.start <= a.ts <= out.end for a in out.alerts)


def test_change_driven_scenarios_record_the_causal_change_at_onset():
    for name, kind in (("bad_deployment", "deploy"), ("config_error", "config_change")):
        scenario = get_scenario(name)
        out = simulate(scenario, seed=1, end=END)
        causal = [
            c
            for c in out.changes
            if c.service == scenario.ground_truth.root_cause_service
            and c.kind == kind
            and c.ts == out.start + timedelta(minutes=scenario.onset_minute)
        ]
        assert causal, f"{name} should record its causal {kind}"


def test_alerts_never_leak_the_scenario_name():
    for name in ALL:
        out = simulate(get_scenario(name), seed=1, end=END)
        for alert in out.alerts:
            assert name not in alert.message and name not in str(alert.labels)


def test_unknown_scenario_lists_available_names():
    with pytest.raises(KeyError, match="Available"):
        get_scenario("nope")
