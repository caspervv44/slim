"""Adapterinterface + mockprovider.

Echte koppelingen (Magister/Osiris/MyX/Somtoday) worden pas gebouwd na
onderzoek per platform (officiële API, OAuth, scopes). Zie docs/architecture.
Deze module definieert het contract waar elke adapter aan moet voldoen.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Protocol

from wekker.agenda.models import Lesson


class AgendaProvider(Protocol):
    name: str

    def fetch_day(self, day: date) -> list[Lesson]:
        """Haal de lessen van één dag op. Gooit ProviderError bij falen.

        Contract voor echte adapters: lessen zijn timezone-aware en uitgedrukt
        in de lokale systeemtijdzone van de wekker (dezelfde basis als de
        Clock), zodat het display tijden zonder conversie kan tonen.
        """
        ...


class ProviderError(Exception):
    """Agenda ophalen mislukt (netwerk/auth/parsing)."""


class MockAgendaProvider:
    """Deterministische neprooster voor laptop/tests.

    Maandag t/m vrijdag: 4 lessen; weekend: leeg. Met ``fail=True`` simuleer
    je een netwerkfout voor de foutafhandeling-test.
    """

    name = "mock"

    def __init__(self, tz: str = "Europe/Amsterdam", fail: bool = False) -> None:
        try:
            from zoneinfo import ZoneInfo

            self._tz = ZoneInfo(tz)
        except Exception:
            # Windows-laptop zonder tzdata: val terug op UTC+1 (alleen mock).
            self._tz = timezone(timedelta(hours=1))
        self.fail = fail

    def fetch_day(self, day: date) -> list[Lesson]:
        if self.fail:
            raise ProviderError("Mock-netwerkfout (gesimuleerd)")
        if day.weekday() >= 5:
            return []
        vakken = [
            ("Wiskunde", "J. Jansen", "A101"),
            ("Nederlands", "P. Pietersen", "B202"),
            ("Engels", "S. Smit", "C303"),
            ("Natuurkunde", "K. Karelse", "D404"),
        ]
        lessen = []
        start = datetime.combine(day, time(8, 30), tzinfo=self._tz)
        for i, (vak, docent, lokaal) in enumerate(vakken):
            s = start + timedelta(minutes=i * 60)
            lessen.append(
                Lesson(subject=vak, start=s, end=s + timedelta(minutes=50),
                       teacher=docent, room=lokaal, source="mock")
            )
        return lessen


def create_provider(name: str) -> AgendaProvider:
    """Maak de adapter voor een gekozen schoolplatform.

    Alleen "mock" heeft een werkende adapter. Andere platforms uit
    ALLOWED_PROVIDERS zijn voorbereid maar geven een duidelijke
    ProviderError ("nog niet beschikbaar") — nooit een stilzwijgende
    lege agenda. Hier komt later OAuth/token-authenticatie per platform.
    """
    if name == "mock":
        return MockAgendaProvider()
    raise ProviderError(
        f"Agenda-provider {name!r} is nog niet beschikbaar; "
        "kies 'mock' voor gesimuleerde gegevens."
    )


class _UnavailableProvider:
    """Plaatshouder-adapter: elke sync mislukt met een eerlijke melding."""

    def __init__(self, wanted: str) -> None:
        self.name = wanted

    def fetch_day(self, day: date) -> list[Lesson]:
        raise ProviderError(
            f"Agenda-provider {self.name!r} is nog niet beschikbaar; "
            "kies 'mock' voor gesimuleerde gegevens."
        )


def create_provider_or_error(name: str) -> AgendaProvider:
    """Adapter bouwen zonder ooit te crashen: onbekende platforms geven een
    plaatshouder waarvan elke sync eerlijk mislukt (cache wordt error/stale).
    """
    try:
        return create_provider(name)
    except ProviderError:
        return _UnavailableProvider(name)
