"""Incident notifications (one message per incident, never per alert)."""

from __future__ import annotations

import logging
from typing import Any, Protocol

log = logging.getLogger(__name__)


class Notifier(Protocol):
    async def notify(self, state: dict[str, Any]) -> None: ...


class LogNotifier:
    """Fallback notifier that only logs; used when no channel is configured."""

    async def notify(self, state: dict[str, Any]) -> None:
        log.info("incident %s: %s", state.get("incident_id"), state.get("summary"))
