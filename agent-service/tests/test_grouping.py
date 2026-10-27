import pytest

from rootsignal_agent.grouping import AlertGrouper
from rootsignal_common.embeddings import HashEmbedder
from rootsignal_sim.engine import simulate
from rootsignal_sim.scenarios import SCENARIOS, get_scenario
from rootsignal_sim.testing import as_events


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def grouper(clock, **kw):
    return AlertGrouper(HashEmbedder(), clock=clock, **{"window_seconds": 20, "quiet_seconds": 6, **kw})


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_each_storm_becomes_one_incident_and_noise_stays_separate(name):
    clock = Clock()
    g = grouper(clock)
    events = as_events(simulate(get_scenario(name), seed=1))
    for event in events:
        clock.now += 0.2
        g.add(event)
    clock.now += 10
    groups = g.due()
    real_ids = {e["id"] for e in events if not e["noise"]}
    main = max(groups, key=lambda grp: len(grp.alerts))
    assert {a["id"] for a in main.alerts} == real_ids, "every storm alert should land in one group"
    assert not any(e["noise"] for e in main.alerts), "the background alert must not be absorbed"


def test_duplicate_fingerprint_joins_even_without_topology():
    clock = Clock()
    g = grouper(clock)
    base = {"service": "auth", "severity": "LOW", "message": "x", "labels": {}, "fingerprint": "fp1"}
    assert g.add({**base, "id": "1"}).kind == "new"
    placement = g.add({**base, "id": "2", "service": "inventory"})
    assert placement.kind == "joined" and placement.reason == "duplicate fingerprint"


def test_group_flushes_after_quiet_period():
    clock = Clock()
    g = grouper(clock, quiet_seconds=5, window_seconds=12)
    g.add({"id": "1", "service": "checkout", "severity": "HIGH", "message": "errors", "labels": {}})
    clock.now = 4
    assert g.due() == []
    clock.now = 5.5
    assert len(g.due()) == 1


def test_busy_group_is_closed_by_the_window_cap():
    clock = Clock()
    g = grouper(clock, quiet_seconds=5, window_seconds=12)
    flushed_at = None
    for t in range(20):  # an alert every second: never quiet
        clock.now = float(t)
        g.add(
            {
                "id": f"x{t}",
                "service": "auth",
                "severity": "HIGH",
                "message": "auth errors",
                "labels": {},
                "fingerprint": "same",
            }
        )
        if g.due():
            flushed_at = t
            break
    assert flushed_at == 12


def test_late_alert_attaches_to_closed_group_within_window():
    clock = Clock()
    g = grouper(clock, quiet_seconds=1, attach_seconds=60)
    g.add(
        {
            "id": "1",
            "service": "checkout",
            "severity": "HIGH",
            "message": "HighErrorRate checkout",
            "labels": {},
            "fingerprint": "fp",
        }
    )
    clock.now = 2
    (closed,) = g.due()
    closed.incident_id = "inc-1"
    clock.now = 30
    placement = g.add(
        {
            "id": "2",
            "service": "checkout",
            "severity": "HIGH",
            "message": "HighErrorRate checkout",
            "labels": {},
            "fingerprint": "fp",
        }
    )
    assert placement.kind == "attach" and placement.group is closed
    clock.now = 200
    assert (
        g.add(
            {
                "id": "3",
                "service": "checkout",
                "severity": "HIGH",
                "message": "HighErrorRate checkout",
                "labels": {},
                "fingerprint": "fp",
            }
        ).kind
        == "new"
    )
