"""Persistente agendacache: laatste bekende rooster + eerlijke syncstatus."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import logging
from pathlib import Path
import threading
import time
from typing import Any

from wekker.agenda.models import Lesson
from wekker.storage import JsonStore, StorageError

log = logging.getLogger(__name__)

STALE_AFTER = timedelta(hours=24)
SCHEMA_VERSION = 2


@dataclass
class AgendaCache:
    """Threadveilige cache die optioneel naar JSON wordt gespiegeld.

    ``last_sync`` blijft bestaan voor backwards compatibility en betekent in
    v8 uitsluitend *laatste geslaagde sync*. ``last_attempt`` wordt apart
    bijgehouden zodat een mislukte poging oude data niet ten onrechte vers maakt.
    """

    days: dict[str, list[Lesson]] = field(default_factory=dict)
    last_sync: datetime | None = None
    status: str = "never"  # never | ok | error | syncing
    error: str | None = None
    last_attempt: datetime | None = None
    loaded_days: set[str] = field(default_factory=set)
    path: str | Path | None = None

    def __post_init__(self) -> None:
        self._lock = threading.RLock()
        self._store = JsonStore(self.path) if self.path is not None else None
        if self._store is not None:
            self._load_persisted()

    @property
    def last_success(self) -> datetime | None:
        return self.last_sync

    def put_day(self, day: date, lessons: list[Lesson]) -> None:
        with self._lock:
            key = day.isoformat()
            self.days[key] = sorted(lessons, key=lambda les: les.start)
            self.loaded_days.add(key)

    def put_days(self, mapping: dict[date, list[Lesson]]) -> None:
        with self._lock:
            for day, lessons in mapping.items():
                key = day.isoformat()
                self.days[key] = sorted(lessons, key=lambda les: les.start)
                self.loaded_days.add(key)

    def get_day(self, day: date) -> list[Lesson]:
        with self._lock:
            return list(self.days.get(day.isoformat(), []))

    def is_day_loaded(self, day: date) -> bool:
        with self._lock:
            return day.isoformat() in self.loaded_days

    def mark_attempt(self, now: datetime) -> None:
        with self._lock:
            self.last_attempt = now
            self.status = "syncing"
            self.error = None
            self._persist()

    def mark_ok(self, now: datetime) -> None:
        with self._lock:
            self.last_attempt = now
            self.last_sync = now
            self.status = "ok"
            self.error = None
            self._persist()

    def mark_error(self, now: datetime, message: str) -> None:
        with self._lock:
            self.last_attempt = now
            self.status = "error"
            self.error = str(message)[:200]
            # last_sync blijft bewust de laatste succesvolle sync.
            self._persist()

    def is_stale(self, now: datetime) -> bool:
        with self._lock:
            last = self.last_sync
        if last is None:
            return True
        try:
            return (now - last) > STALE_AFTER
        except TypeError:
            return True

    def display_status(self, now: datetime) -> str:
        """Menselijke roosterstatus voor B4."""
        with self._lock:
            status = self.status
            last = self.last_sync
        if status == "syncing":
            return "Rooster wordt bijgewerkt…"
        if last is None:
            if status == "error":
                return "Nog niet geladen"
            return "Nog niet geladen"
        local = last.astimezone(now.tzinfo) if now.tzinfo and last.tzinfo else last
        stamp = local.strftime("%H:%M")
        if status == "error" or self.is_stale(now):
            return f"Eerder rooster getoond · bijgewerkt om {stamp}"
        return f"Bijgewerkt om {stamp}"

    def status_dict(self) -> dict:
        with self._lock:
            return {
                "status": self.status,
                "last_sync": self.last_sync.isoformat() if self.last_sync else None,
                "last_success": self.last_sync.isoformat() if self.last_sync else None,
                "last_attempt": self.last_attempt.isoformat() if self.last_attempt else None,
                "error": self.error,
                "cached_days": sorted(self.days.keys()),
                "loaded_days": sorted(self.loaded_days),
            }

    def _persist(self) -> None:
        if self._store is None:
            return
        data = {
            "schema_version": SCHEMA_VERSION,
            "last_success": self.last_sync.isoformat() if self.last_sync else None,
            "last_attempt": self.last_attempt.isoformat() if self.last_attempt else None,
            "status": self.status,
            "error": self.error,
            "loaded_days": sorted(self.loaded_days),
            "days": {
                day: [lesson.to_dict() for lesson in lessons]
                for day, lessons in self.days.items()
            },
        }
        try:
            self._store.save(data)
        except StorageError:
            log.exception("agendacache kon niet persistent worden opgeslagen")

    def _load_persisted(self) -> None:
        assert self._store is not None
        try:
            raw = self._store.load()
        except StorageError as exc:
            self._quarantine_corrupt()
            log.warning("agendacache onleesbaar; lege cache gebruikt: %s", exc)
            return
        if raw is None:
            return
        try:
            schema = int(raw.get("schema_version", 0))
            if schema not in {1, SCHEMA_VERSION}:
                raise ValueError("onbekende schema-versie")
            days_raw = raw.get("days", {})
            if not isinstance(days_raw, dict):
                raise ValueError("days moet een object zijn")
            loaded: dict[str, list[Lesson]] = {}
            for key, records in days_raw.items():
                date.fromisoformat(str(key))
                if not isinstance(records, list):
                    raise ValueError("dagrecord moet een lijst zijn")
                loaded[str(key)] = [Lesson.from_dict(item) for item in records]
            self.days = loaded
            loaded_days = raw.get("loaded_days")
            if isinstance(loaded_days, list):
                self.loaded_days = {str(item) for item in loaded_days}
            else:
                # Migratie van v1: iedere opgeslagen dag was aantoonbaar geladen.
                self.loaded_days = set(loaded)
            last_success = raw.get("last_success") or raw.get("last_sync")
            self.last_sync = (
                datetime.fromisoformat(str(last_success)) if last_success else None
            )
            last_attempt = raw.get("last_attempt")
            self.last_attempt = (
                datetime.fromisoformat(str(last_attempt)) if last_attempt else self.last_sync
            )
            self.status = str(raw.get("status") or ("ok" if self.last_sync else "never"))
            if self.status not in {"never", "ok", "error", "syncing"}:
                self.status = "error"
            self.error = str(raw.get("error"))[:200] if raw.get("error") else None
        except Exception as exc:
            self.days = {}
            self.loaded_days = set()
            self.last_sync = None
            self.last_attempt = None
            self.status = "never"
            self.error = None
            self._quarantine_corrupt()
            log.warning("agendacache ongeldig; lege cache gebruikt: %s", exc)

    def _quarantine_corrupt(self) -> None:
        if self.path is None:
            return
        path = Path(self.path)
        if not path.exists():
            return
        target = path.with_name(
            f"{path.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}"
        )
        try:
            path.replace(target)
        except OSError:
            pass
