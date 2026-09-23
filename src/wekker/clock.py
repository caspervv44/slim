"""Tijdvoorziening achter een interface.

De productieklok kan een expliciete IANA-tijdzone gebruiken. Daardoor volgt
de klokinstelling op het touchscreen niet per ongeluk de Linux-systeemzone.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo


class Clock(Protocol):
    def now(self) -> datetime:
        """Geef de huidige lokale tijd (timezone-aware)."""
        ...


class SystemClock:
    """Productieklok met runtime-wijzigbare IANA-tijdzone."""

    def __init__(self, timezone_name: str | None = None) -> None:
        self._timezone_name = timezone_name
        self._timezone = ZoneInfo(timezone_name) if timezone_name else None

    @property
    def timezone_name(self) -> str | None:
        return self._timezone_name

    def set_timezone(self, timezone_name: str) -> None:
        # Validatie gebeurt al in Settings; ZoneInfo blijft hier bewust de
        # laatste verdedigingslaag wanneer SystemClock los wordt gebruikt.
        self._timezone = ZoneInfo(timezone_name)
        self._timezone_name = timezone_name

    def now(self) -> datetime:
        if self._timezone is None:
            return datetime.now().astimezone()
        return datetime.now(self._timezone)


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
