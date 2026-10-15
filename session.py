"""Advertisement aggregation and stabilization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable
from uuid import UUID, uuid4

from .parser import ParsedMeasurement


@dataclass(slots=True)
class MeasurementSession:
    session_uuid: UUID
    started_at: datetime
    last_seen_at: datetime
    latest: ParsedMeasurement
    advertisement_count: int = 1
    finalized: bool = False


class SessionAggregator:
    """Keep one open session per scale and finalize a stable reading once."""

    def __init__(self, window_seconds: int = 30, clock: Callable[[], datetime] | None = None):
        self.window = timedelta(seconds=max(1, window_seconds))
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sessions: dict[str, MeasurementSession] = {}
        self.last_finalized: MeasurementSession | None = None

    def ingest(self, reading: ParsedMeasurement) -> ParsedMeasurement | None:
        now = self._clock()
        current = self._sessions.get(reading.mac_address)
        if current is None or now - current.last_seen_at > self.window:
            current = MeasurementSession(uuid4(), now, now, reading)
            self._sessions[reading.mac_address] = current
        else:
            current.last_seen_at = now
            current.latest = reading
            current.advertisement_count += 1
        if not reading.stable or current.finalized:
            return None
        current.finalized = True
        self.last_finalized = current
        return current.latest

    def expire(self) -> None:
        now = self._clock()
        for mac, current in list(self._sessions.items()):
            if now - current.last_seen_at > self.window:
                self._sessions.pop(mac, None)
