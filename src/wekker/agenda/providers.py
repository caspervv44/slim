"""Adapterinterface, provider-register en mockprovider.

Nieuwe schoolplatformen worden toegevoegd als (AuthProvider, AgendaProvider)
paar in :data:`PROVIDER_INFOS` + een tak in :func:`create_provider`. De core,
GUI en webinterface kennen alleen deze generieke interface — geen
``if school == ...`` in algemene code.
"""

from __future__ import annotations

from dataclasses import dataclass
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


def create_provider(name: str, auth_store=None, myx_auth=None) -> AgendaProvider:
    """Maak de adapter voor een gekozen schoolplatform.

    - ``"mock"``: altijd werkend, gesimuleerde gegevens.
    - ``"osiris"``: ROC Aventus; vereist een koppeling (zie ``auth.py`` en
      ``osiris.py``). Zonder koppeling mislukt syncen met een koppel-hint.
    - overige namen uit ALLOWED_PROVIDERS: voorbereid maar nog niet
      beschikbaar → duidelijke ProviderError, nooit een stilzwijgende lege
      agenda.
    """
    if name == "mock":
        return MockAgendaProvider()
    if name == "osiris":
        from wekker.agenda.osiris import OsirisAgendaProvider

        if auth_store is None:
            raise ProviderError(
                "Osiris vereist een koppeling; er is geen auth-store beschikbaar."
            )
        return OsirisAgendaProvider(auth_store)
    if name == "myx":
        from wekker.agenda.myx import MyXAgendaProvider

        return MyXAgendaProvider(config_loader=myx_auth.ensure_config if myx_auth else None)
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


def create_provider_or_error(name: str, auth_store=None, myx_auth=None) -> AgendaProvider:
    """Adapter bouwen zonder ooit te crashen: onbekende platforms geven een
    plaatshouder waarvan elke sync eerlijk mislukt (cache wordt error/stale).
    """
    try:
        return create_provider(name, auth_store, myx_auth)
    except ProviderError:
        return _UnavailableProvider(name)


def build_sync_provider(provider_id: str, cache, clock, auth_store=None, myx_auth=None):
    """Maak een :class:`AgendaSyncService` voor een provider-id. Enige plek
    waar settings-providernaam → adaptervertaling gebeurt (main, API, tests)."""
    from wekker.agenda.sync import AgendaSyncService

    return AgendaSyncService(create_provider_or_error(provider_id, auth_store, myx_auth),
                             cache, clock)


@dataclass(frozen=True)
class ProviderInfo:
    """Beschrijving van één schoolplatform voor GUI/webinterface.

    Alleen generieke metadata — géén school-specifieke logica elders nodig.
    ``auth`` is ``"none"`` of ``"entree-oidc"``; ``available`` geeft aan of
    het platform in deze versie echt (of als demo) te koppelen is.
    """

    id: str
    display_name: str
    school: str
    auth: str
    available: bool
    description: str


PROVIDER_INFOS: dict[str, ProviderInfo] = {
    "mock": ProviderInfo(
        id="mock",
        display_name="Mock (voorbeeldgegevens)",
        school="—",
        auth="none",
        available=True,
        description="Vaste voorbeeldlessen, altijd gesimuleerd.",
    ),
    "osiris": ProviderInfo(
        id="osiris",
        display_name="OSIRIS – ROC Aventus",
        school="ROC Aventus",
        auth="entree-oidc",
        available=True,
        description="Echte koppeling via Entree-login (in voorbereiding; nu demo).",
    ),
    "somtoday": ProviderInfo(
        id="somtoday",
        display_name="Somtoday",
        school="—",
        auth="entree-oidc",
        available=False,
        description="Later toe te voegen provider.",
    ),
    "magister": ProviderInfo(
        id="magister",
        display_name="Magister",
        school="—",
        auth="entree-oidc",
        available=False,
        description="Later toe te voegen provider.",
    ),
    "myx": ProviderInfo(
        id="myx",
        display_name="MyX / Xedule – Aventus",
        school="Aventus",
        auth="browser-sso",
        available=True,
        description="MyX-login op de wekker; tokens worden automatisch beheerd.",
    ),
}


def list_providers() -> list[ProviderInfo]:
    """Alle bekende platforms, in vaste volgorde voor de UI."""
    return [PROVIDER_INFOS[k] for k in ("mock", "osiris", "somtoday", "magister", "myx")]


def get_provider_info(provider_id: str) -> ProviderInfo:
    """Metadata voor één platform; onbekende id geeft ValueError."""
    try:
        return PROVIDER_INFOS[provider_id]
    except KeyError as exc:
        raise ValueError(f"Onbekende provider: {provider_id!r}") from exc
