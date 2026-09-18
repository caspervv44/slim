"""Osiris-provider voor ROC Aventus (voorbereidende implementatie).

Status: er is nog géén echte Osiris/Entree-koppeling. Deze provider:
- vereist een koppeling via :class:`AuthService` (zie ``auth.py``);
- geeft zonder koppeling een duidelijke fout met koppel-instructie;
- geeft mét (demo-)koppeling duidelijk gemarkeerde demodata
  (``source="osiris-demo"``), zodat GUI en webinterface end-to-end werken
  zonder GUI-refactor zodra de echte API er is.

Er worden geen endpoints, client-ID's, scopes of tokens aangenomen; zie
``docs/osiris-entree.md`` voor wat er nog nodig is.
"""

from __future__ import annotations

from datetime import date

from wekker.agenda.auth import AuthService
from wekker.agenda.models import Lesson
from wekker.agenda.providers import MockAgendaProvider, ProviderError

#: Bronlabel voor demo-lessen via deze provider (altijd gesimuleerd).
OSIRIS_DEMO_SOURCE = "osiris-demo"


class OsirisAgendaProvider:
    """Agenda-adapter voor OSIRIS / ROC Aventus."""

    name = "osiris"

    def __init__(self, auth: AuthService) -> None:
        self._auth = auth
        self._demo = MockAgendaProvider()

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
