"""Persistente runtime-status voor het alarm.

De normale instellingen beschrijven *wat* het alarm moet doen. Dit bestand
onthoudt alleen de actuele toestand die een herstart moet overleven, zoals een
lopende snooze of een alarm dat vandaag al is afgehandeld.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
import time
from typing import Any

from wekker.storage import JsonStore, StorageError

log = logging.getLogger(__name__)
SCHEMA_VERSION = 3


@dataclass
class AlarmRuntimeSnapshot:
    state: str = "sleeping"
    ringing_since: str | None = None
    snooze_until: str | None = None
    last_trigger_date: str | None = None
    dismissed_date: str | None = None
    missed_notice: str = ""
    # Alleen gezet als WakeSync een alarm als gemist markeerde zonder dat de
    # gebruiker het fysiek heeft afgehandeld. Hiermee kan een achterwaartse
    # klokcorrectie vóór de echte alarmtijd veilig worden hersteld.
    missed_date: str | None = None
    # v10: meerdere onafhankelijke alarmen. De legacyvelden hierboven blijven
    # staan zodat oude runtimebestanden veilig gemigreerd kunnen worden.
    active_alarm_id: str | None = None
    last_trigger_dates: dict[str, str] | None = None
    dismissed_dates: dict[str, str] | None = None
    missed_dates: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "state": self.state,
            "ringing_since": self.ringing_since,
            "snooze_until": self.snooze_until,
            "last_trigger_date": self.last_trigger_date,
            "dismissed_date": self.dismissed_date,
            "missed_notice": self.missed_notice,
            "missed_date": self.missed_date,
            "active_alarm_id": self.active_alarm_id,
            "last_trigger_dates": dict(self.last_trigger_dates or {}),
            "dismissed_dates": dict(self.dismissed_dates or {}),
            "missed_dates": dict(self.missed_dates or {}),
        }


class AlarmRuntimeStore:
    """Atomische opslag met veilige terugval bij een corrupt bestand."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._store = JsonStore(self.path)

    def load(self) -> AlarmRuntimeSnapshot | None:
        try:
            raw = self._store.load()
        except StorageError as exc:
            self._quarantine_corrupt()
            log.warning("alarmstatus was onleesbaar en is apart gezet: %s", exc)
            return None
        if raw is None:
            return None
        try:
            schema = int(raw.get("schema_version", 0))
            if schema not in {1, 2, SCHEMA_VERSION}:
                raise ValueError("onbekende schema-versie")
            state = str(raw.get("state", "sleeping"))
            if state not in {"sleeping", "ringing", "snoozed", "dismissed"}:
                raise ValueError("ongeldige alarmtoestand")
            # ISO-waarden alvast syntactisch valideren.
            for key in ("ringing_since", "snooze_until"):
                value = raw.get(key)
                if value:
                    datetime.fromisoformat(str(value))
            def _strmap(name: str) -> dict[str, str]:
                value = raw.get(name, {}) if schema >= 3 else {}
                if not isinstance(value, dict):
                    raise ValueError(f"{name} moet een object zijn")
                return {
                    str(k): str(v)
                    for k, v in value.items()
                    if str(k).strip() and str(v).strip()
                }

            return AlarmRuntimeSnapshot(
                state=state,
                ringing_since=_opt_str(raw.get("ringing_since")),
                snooze_until=_opt_str(raw.get("snooze_until")),
                last_trigger_date=_opt_str(raw.get("last_trigger_date")),
                dismissed_date=_opt_str(raw.get("dismissed_date")),
                missed_notice=str(raw.get("missed_notice") or "")[:200],
                missed_date=_opt_str(raw.get("missed_date")) if schema >= 2 else None,
                active_alarm_id=_opt_str(raw.get("active_alarm_id")) if schema >= 3 else None,
                last_trigger_dates=_strmap("last_trigger_dates"),
                dismissed_dates=_strmap("dismissed_dates"),
                missed_dates=_strmap("missed_dates"),
            )
        except Exception as exc:
            self._quarantine_corrupt()
            log.warning("alarmstatus was ongeldig en is apart gezet: %s", exc)
            return None

    def save(self, snapshot: AlarmRuntimeSnapshot) -> None:
        self._store.save(snapshot.to_dict())

    def _quarantine_corrupt(self) -> None:
        if not self.path.exists():
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
        try:
            self.path.replace(target)
        except OSError:
            pass


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value)
    return value or None
