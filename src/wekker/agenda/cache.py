"""Agendacache: laatste bekende rooster + syncstatus."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from wekker.agenda.models import Lesson

# Na deze leeftijd geldt cached rooster als mogelijk verouderd. 24 uur: het
# dagrooster van vandaag is 's ochtends vers gesynchroniseerd nog geldig,
# maar een sync van eergisteren duidelijk niet meer.
STALE_AFTER = timedelta(hours=24)


@dataclass
class AgendaCache:
    days: dict[str, list[Lesson]] = field(default_factory=dict)
    last_sync: datetime | None = None
    status: str = "never"  # never | ok | error
    error: str | None = None

    def put_day(self, day: date, lessons: list[Lesson]) -> None:
        self.days[day.isoformat()] = sorted(lessons, key=lambda les: les.start)

    def get_day(self, day: date) -> list[Lesson]:
        return list(self.days.get(day.isoformat(), []))

    def mark_ok(self, now: datetime) -> None:
        self.last_sync = now
        self.status = "ok"
        self.error = None

    def mark_error(self, now: datetime, message: str) -> None:
        self.last_sync = now
        self.status = "error"
        # Bewust kort: volledige tracebacks horen niet in de status-API.
        self.error = message[:200]

    def is_stale(self, now: datetime) -> bool:
        """True als het rooster mogelijk verouderd is.

        Nooit gesynchroniseerd → altijd stale. Een mislukte sync zet de
        status op 'error' maar wist de cache niet: de lessen blijven
        beschikbaar, gemarkeerd als mogelijk verouderd.
        """
        if self.last_sync is None:
            return True
        try:
            return (now - self.last_sync) > STALE_AFTER
        except TypeError:
            # naive vs. aware datetimes (klokfout): veilig als stale melden.
            return True

    def status_dict(self) -> dict:
        return {
            "status": self.status,
            "last_sync": self.last_sync.isoformat() if self.last_sync else None,
            "error": self.error,
            "cached_days": sorted(self.days.keys()),
        }
