"""Tijdvoorziening achter een interface.

De wekker-core mag nooit direct ``datetime.now()`` aanroepen, zodat tests
met een neptijd deterministisch zijn en de Pi later een eigen bron
(bv. RTC/NTP-gesynchroniseerde klok) kan injecteren.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    """Minimale klok-interface voor de core en display."""

    def now(self) -> datetime:
        """Geef de huidige lokale tijd (timezone-aware)."""
        ...


class SystemClock:
    """Productieklok: de systeemklok van laptop of Raspberry Pi."""

    def now(self) -> datetime:
        return datetime.now().astimezone()


class FakeClock:
    """Bestuurbare klok voor tests en demo's."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FakeClock vereist een timezone-aware datetime")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def set(self, moment: datetime) -> None:
        if moment.tzinfo is None:
            raise ValueError("FakeClock vereist een timezone-aware datetime")
        self._now = moment

    def advance(self, delta: timedelta) -> datetime:
        self._now = self._now + delta
        return self._now
