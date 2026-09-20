"""Prototype-login voor de lokale webinterface.

Dit is uitdrukkelijk géén productiebeveiliging, alleen een drempel voor het
prototype op het lokale netwerk:

- vaste development-credentials (casper/casper), nergens anders gebruikt;
- sessies via een HttpOnly-cookie, 12 uur geldig, alleen in het geheugen;
- wachtwoorden worden nooit gelogd, nooit opgeslagen en nooit teruggestuurd.

Dit staat los van ``wekker.agenda.auth`` (koppelingen met schoolplatformen);
daar worden juist nooit wachtwoorden geaccepteerd.
"""

from __future__ import annotations

import hmac
import logging
import secrets
import threading
from datetime import datetime, timedelta

from wekker.clock import Clock

log = logging.getLogger(__name__)

#: Development-credentials voor het prototype. Alleen voor lokaal gebruik.
PROTOTYPE_USERNAME = "casper"
PROTOTYPE_PASSWORD = "casper"

#: Cookienaam voor de websessie.
SESSION_COOKIE = "wekker_session"

#: Hoe lang een ingelogde sessie geldig blijft.
SESSION_TTL = timedelta(hours=12)


class WebAuthError(Exception):
    """Inloggen of sessie mislukt (altijd generieke melding naar de client)."""


class SessionStore:
    """Sessies in het geheugen: token → verlooptijd. Na een herstart moet
    opnieuw worden ingelogd (bewust: geen persistente sessies)."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._tokens: dict[str, datetime] = {}

    def login(self, username: object, password: object) -> str:
        """Controleer credentials; geef bij succes een sessietoken terug.

        Bij falen altijd dezelfde generieke fout (geen user-enumeration) en
        er wordt nooit een wachtwoord of token gelogd.
        """
        ok_user = isinstance(username, str) and hmac.compare_digest(
            username, PROTOTYPE_USERNAME
        )
        ok_pass = isinstance(password, str) and hmac.compare_digest(
            password, PROTOTYPE_PASSWORD
        )
        if not (ok_user and ok_pass):
            log.info("web-login mislukt")
            raise WebAuthError("Onjuiste inloggegevens.")
        with self._lock:
            self._prune_locked()
            token = secrets.token_urlsafe(32)
            self._tokens[token] = self._clock.now() + SESSION_TTL
            return token

    def valid(self, token: object) -> bool:
        if not isinstance(token, str) or not token:
            return False
        with self._lock:
            verloopt = self._tokens.get(token)
            if verloopt is None:
                return False
            if self._clock.now() > verloopt:
                del self._tokens[token]
                return False
            return True

    def logout(self, token: object) -> bool:
        """Trek een sessie in. Geeft True als er een sessie was."""
        if not isinstance(token, str) or not token:
            return False
        with self._lock:
            return self._tokens.pop(token, None) is not None

    def _prune_locked(self) -> None:
        now = self._clock.now()
        verlopen = [t for t, tot in self._tokens.items() if now > tot]
        for t in verlopen:
            del self._tokens[t]


def parse_cookies(header: str | None) -> dict[str, str]:
    """Parse een Cookie-header naar {naam: waarde}. Negeert rommel stil."""
    cookies: dict[str, str] = {}
    if not header:
        return cookies
    for deel in header.split(";"):
        if "=" not in deel:
            continue
        naam, _, waarde = deel.partition("=")
        naam = naam.strip()
        if naam:
            cookies[naam] = waarde.strip().strip('"')
    return cookies
