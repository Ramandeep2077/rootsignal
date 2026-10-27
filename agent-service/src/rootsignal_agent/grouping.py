"""Alert grouping: turns a stream of raw alerts into groups that each become one incident.

An alert joins an existing group when any of these hold:

- **Fingerprint**: an exact duplicate (same source/service/message modulo numbers & ids) is already in the group.
- **Semantic similarity**: cosine similarity between the alert's embedding and the group's centroid
  is at least ``similarity_threshold`` (local all-MiniLM-L6-v2 embeddings).
- **Topology**: the alert's service is the same as, or a direct caller/callee of, a service in the group, and
  both the alert and the group are at least MEDIUM severity. Symptoms of one failure spread along the
  dependency graph; low-severity background alerts are *not* pulled in by adjacency alone.

A group closes ("flushes") after ``quiet_seconds`` without new members or ``window_seconds`` after it opened,
and becomes an incident. Alerts arriving within ``attach_seconds`` that match a closed group are attached to
its existing incident instead of opening a new one.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from rootsignal_common.embeddings import Embedder
from rootsignal_common.taxonomy import DEPENDENCIES

SEVERE = {"CRITICAL", "HIGH", "MEDIUM"}


def related(a: str, b: str) -> bool:
    return a == b or b in DEPENDENCIES.get(a, ()) or a in DEPENDENCIES.get(b, ())


def embedding_text(alert: dict[str, Any]) -> str:
    name = alert.get("labels", {}).get("alertname", "")
    return f"{alert['service']} {name}: {alert['message']}"


@dataclass
class AlertGroup:
    id: str
    alerts: list[dict[str, Any]]
    services: set[str]
    fingerprints: set[str]
    vector_sum: np.ndarray
    opened: float
    updated: float
    incident_id: str | None = None
    closed_at: float | None = None
    pending_attach: list[dict[str, Any]] = field(default_factory=list)

    @property
    def centroid(self) -> np.ndarray:
        norm = np.linalg.norm(self.vector_sum)
        return self.vector_sum / norm if norm else self.vector_sum

    @property
    def severe(self) -> bool:
        return any(a["severity"] in SEVERE for a in self.alerts)

    def add(self, alert: dict[str, Any], vector: np.ndarray, now: float) -> None:
        self.alerts.append(alert)
        self.services.add(alert["service"])
        self.fingerprints.add(alert.get("fingerprint", ""))
        self.vector_sum = self.vector_sum + vector
        self.updated = now


@dataclass
class Placement:
    group: AlertGroup
    kind: str  # "new" | "joined" | "attach"
    reason: str


class AlertGrouper:
    def __init__(
        self,
        embedder: Embedder,
        *,
        similarity_threshold: float = 0.55,
        window_seconds: float = 20.0,
        quiet_seconds: float = 6.0,
        attach_seconds: float = 600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.embedder = embedder
        self.threshold = similarity_threshold
        self.window = window_seconds
        self.quiet = quiet_seconds
        self.attach = attach_seconds
        self.clock = clock
        self.open: list[AlertGroup] = []
        self.closed: list[AlertGroup] = []

    def _match(
        self, group: AlertGroup, alert: dict[str, Any], vector: np.ndarray
    ) -> tuple[float, str] | None:
        if alert.get("fingerprint") and alert["fingerprint"] in group.fingerprints:
            return 2.0, "duplicate fingerprint"
        similarity = float(np.dot(vector, group.centroid))
        topology = any(related(alert["service"], s) for s in group.services)
        if topology and alert["severity"] in SEVERE and group.severe:
            return 1.0 + similarity, f"related service (similarity {similarity:.2f})"
        if similarity >= self.threshold:
            return similarity, f"similar alert text ({similarity:.2f})"
        return None

    def add(self, alert: dict[str, Any]) -> Placement:
        now = self.clock()
        self._expire(now)
        vector = self.embedder.embed([embedding_text(alert)])[0]
        for pool, kind in ((self.open, "joined"), (self.closed, "attach")):
            scored = [(m, g) for g in pool if (m := self._match(g, alert, vector))]
            if scored:
                (_score, reason), group = max(scored, key=lambda item: item[0][0])
                group.add(alert, vector, now)
                if kind == "attach":
                    group.pending_attach.append(alert)
                return Placement(group, kind, reason)
        group = AlertGroup(str(uuid.uuid4()), [], set(), set(), np.zeros_like(vector), now, now)
        group.add(alert, vector, now)
        self.open.append(group)
        return Placement(group, "new", "no matching group")

    def due(self) -> list[AlertGroup]:
        """Groups ready to become incidents. They move to ``closed`` so late alerts can still attach."""
        now = self.clock()
        ready = [g for g in self.open if now - g.updated >= self.quiet or now - g.opened >= self.window]
        for group in ready:
            self.open.remove(group)
            group.closed_at = now
            self.closed.append(group)
        return ready

    def _expire(self, now: float) -> None:
        self.closed = [g for g in self.closed if g.closed_at is not None and now - g.closed_at < self.attach]
