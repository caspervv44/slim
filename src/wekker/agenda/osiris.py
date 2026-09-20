"""Osiris-provider voor ROC Aventus (voorbereidende implementatie).

Status: er is nog géén echte Osiris/Entree-koppeling. Deze provider:
- vereist een koppeling via :class:`AuthService` (zie ``auth.py``);
- geeft zonder koppeling een duidelijke fout met koppel-instructie;
- geeft mét (demo-)koppeling duidelijk gemarkeerde demodata
  (``source="osiris-demo"``), zodat GUI en webinterface end-to-end werken
  zonder GUI-refactor zodra de echte API er is.

Er worden geen endpoints, client-ID's, scopes of tokens aangenomen; zie
``docs/osiris-entree.md`` voor wat er nog nodig is.

Echte configuratie loopt uitsluitend via environment-variabelen (alleen de
NAMEN staan in code/docs, nooit waarden). Zonder volledige configuratie
meldt de provider eerlijk dat OSIRIS niet geconfigureerd is; Mock blijft
gewoon werken.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date

from wekker.agenda.auth import AuthService
from wekker.agenda.models import Lesson
from wekker.agenda.providers import MockAgendaProvider, ProviderError

log = logging.getLogger(__name__)

#: Bronlabel voor demo-lessen via deze provider (altijd gesimuleerd).
OSIRIS_DEMO_SOURCE = "osiris-demo"

#: Environment-variabelen voor echte OSIRIS-configuratie. Alleen namen;
#: waarden komen van de beheerder en horen nooit in Git, logs of responses.
ENV_OSIRIS_BASE_URL = "WEKKER_OSIRIS_BASE_URL"
ENV_OSIRIS_CLIENT_ID = "WEKKER_OSIRIS_CLIENT_ID"
ENV_OSIRIS_REDIRECT_URI = "WEKKER_OSIRIS_REDIRECT_URI"
REQUIRED_OSIRIS_ENV = (
    ENV_OSIRIS_BASE_URL,
    ENV_OSIRIS_CLIENT_ID,
    ENV_OSIRIS_REDIRECT_URI,
)


@dataclass(frozen=True)
class OsirisConfig:
    """Echte OSIRIS-configuratie, uitsluitend uit environment-variabelen.

    Zolang niet alle vereiste variabelen zijn gezet, is er geen echte
    koppeling mogelijk en blijft de demo-flow (expliciet gelabeld) de enige
    werkende stand. Naar buiten komen alleen ``configured`` en ``missing()``
    (namen, nooit waarden) — zie ``docs/osiris-entree.md``.
    """

    base_url: str = ""
    client_id: str = ""
    redirect_uri: str = ""
    _present: tuple[str, ...] = field(default=(), repr=False, compare=False)

    @classmethod
    def from_env(cls, env=None) -> OsirisConfig:
        bron = env if env is not None else os.environ
        waarden = {naam: (bron.get(naam) or "").strip() for naam in REQUIRED_OSIRIS_ENV}
        aanwezig = tuple(naam for naam, waarde in waarden.items() if waarde)
        return cls(
            base_url=waarden[ENV_OSIRIS_BASE_URL],
            client_id=waarden[ENV_OSIRIS_CLIENT_ID],
            redirect_uri=waarden[ENV_OSIRIS_REDIRECT_URI],
            _present=aanwezig,
        )

    @property
    def configured(self) -> bool:
        """True als alle vereiste variabelen zijn gezet."""
        return len(self._present) == len(REQUIRED_OSIRIS_ENV)

    def missing(self) -> list[str]:
        """Namen van ontbrekende variabelen (nooit waarden)."""
        return [naam for naam in REQUIRED_OSIRIS_ENV if naam not in self._present]


class OsirisAgendaProvider:
    """Agenda-adapter voor OSIRIS / ROC Aventus."""

    name = "osiris"

    def __init__(self, auth: AuthService, config: OsirisConfig | None = None) -> None:
        self._auth = auth
        # Expliciet meegegeven config (tests) of uit de omgeving (productie).
        self._config = config if config is not None else OsirisConfig.from_env()
        self._demo = MockAgendaProvider()

    @property
    def config(self) -> OsirisConfig:
        """Configuratiestatus; echte data vereist ``configured`` én een
        koppeling. De API-vorm is nog onbekend (zie docs), dus blijft de
        demo-bron expliciet gelabeld tot de echte mapping kan worden gebouwd."""
        return self._config

    def fetch_day(self, day: date) -> list[Lesson]:
        link = self._auth.get_link("osiris")
        if link is None:
            raise ProviderError(
                "Osiris is niet gekoppeld. Koppel via de webinterface "
                "('Agenda koppelen' → 'ROC Aventus / Osiris')."
            )
        lessen = self._demo.fetch_day(day)
        # Demodata, expliciet gelabeld; echte API-data krijgt later source="osiris".
        return [
            Lesson(subject=les.subject, start=les.start, end=les.end,
                   teacher=les.teacher, room=les.room, source=OSIRIS_DEMO_SOURCE)
            for les in lessen
        ]
