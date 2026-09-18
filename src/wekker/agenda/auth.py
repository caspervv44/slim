"""Authenticatie-abstractie voor schoolagenda-koppelingen.

Ontwerp:
- De core kent geen scholen (geen ``if school == ...``); per platform is er
  een ``AuthProvider`` plus een ``AgendaProvider`` (zie ``providers.py``).
- Er worden **nooit wachtwoorden** opgeslagen of geaccepteerd. De echte
  Entree/OIDC-flow (later) levert tokens die in veilige opslag horen
  (OS-keyring op de Pi); zie ``docs/osiris-entree.md``.
- ``MockEntreeAuth`` is een demo-implementatie voor development: de flow
  werkt met eenmalige state-tokens, zonder inloggegevens.

Wat hier nog NIET in zit (bewust): echte OIDC-discovery, client-ID's,
scopes, token-endpoints en veilige tokenopslag. Daarvoor ontbreken de
schoolgegevens nog; zie ``docs/osiris-entree.md``.
"""

from __future__ import annotations

import logging
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from wekker.clock import Clock

log = logging.getLogger(__name__)

#: Geldigheidsduur van een gestarte (nog niet afgeronde) login-flow.
FLOW_TTL = timedelta(minutes=10)

#: Maximale lengte van een state-parameter (inputvalidatie, zie API).
MAX_STATE_LEN = 128


@dataclass(frozen=True)
class AuthLink:
    """Bewijs dat een provider gekoppeld is. Bevat géén geheimen."""

    provider_id: str
    account_label: str
    linked_at: str
    demo: bool = False

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "account_label": self.account_label,
            "linked_at": self.linked_at,
            "demo": self.demo,
        }


@dataclass
class AuthFlow:
    """Een gestarte login-flow: browser opent ``auth_url``, wekker rondt af
    via ``complete_flow(state)``."""

    state: str
    auth_url: str
    expires_at: datetime


class AuthProvider(Protocol):
    """Contract voor school-login (later: echte Entree/OIDC)."""

    provider_id: str
    login_label: str

    def start_flow(self, base_url: str) -> AuthFlow:
        """Start een login-flow; geeft URL + eenmalige state terug."""
        ...

    def complete_flow(self, state: str) -> AuthLink:
        """Rond een gestarte flow af. Neemt alleen de state, nooit een
        wachtwoord of gebruikersnaam."""
        ...


@dataclass
class _PendingFlow:
    state: str
    expires_at: datetime


class MockEntreeAuth:
    """Demo-login ("Inloggen met Entree") voor development.

    Simuleert alleen de vorm van de flow (start → browser → callback met
    state). Er bestaan geen echte Entree-gegevens in deze implementatie en
    ``complete_flow`` accepteert uitsluitend een eerder uitgegeven state.
    """

    provider_id = "osiris"
    login_label = "Inloggen met Entree (demo)"

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._pending: dict[str, _PendingFlow] = {}

    def start_flow(self, base_url: str) -> AuthFlow:
        with self._lock:
            self._prune_locked()
            state = secrets.token_urlsafe(24)
            expires_at = self._clock.now() + FLOW_TTL
            self._pending[state] = _PendingFlow(state=state, expires_at=expires_at)
            url = f"{base_url.rstrip('/')}/api/agenda/auth/mock?state={state}"
            log.info("demo-login gestart voor %s", self.provider_id)
            return AuthFlow(state=state, auth_url=url, expires_at=expires_at)

    def complete_flow(self, state: str) -> AuthLink:
        with self._lock:
            flow = self._pending.pop(state, None)
            if flow is None:
                raise AuthError("Onbekende of al gebruikte login-status (state).")
            if self._clock.now() > flow.expires_at:
                raise AuthError("Login-status is verlopen; start opnieuw.")
            log.info("demo-login afgerond voor %s", self.provider_id)
            return AuthLink(
                provider_id=self.provider_id,
                account_label="Demo-student (ROC Aventus)",
                linked_at=self._clock.now().isoformat(),
                demo=True,
            )

    def _prune_locked(self) -> None:
        now = self._clock.now()
        verlopen = [s for s, f in self._pending.items() if now > f.expires_at]
        for s in verlopen:
            del self._pending[s]


class AuthError(Exception):
    """Login-flow mislukt (ongeldige/verlopen/hergebruikte state)."""


@dataclass
class AuthService:
    """Koppelingen beheren: store + auth-providers per platform.

    Slaat alleen :class:`AuthLink` records op (geen wachtwoorden, geen
    tokens in deze versie). Links leven in het geheugen; na een herstart
    moet opnieuw gekoppeld worden (documentatie: zie ``docs/osiris-entree.md``).
    """

    clock: Clock
    providers: dict[str, AuthProvider] = field(default_factory=dict)
    _links: dict[str, AuthLink] = field(default_factory=dict, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def is_linked(self, provider_id: str) -> bool:
        with self._lock:
            return provider_id in self._links

    def get_link(self, provider_id: str) -> AuthLink | None:
        with self._lock:
            return self._links.get(provider_id)

    def link(self, link: AuthLink) -> None:
        with self._lock:
            self._links[link.provider_id] = link

    def disconnect(self, provider_id: str) -> bool:
        """Verbreek een koppeling. Geeft True als er een was."""
        with self._lock:
            return self._links.pop(provider_id, None) is not None

    def start_flow(self, provider_id: str, base_url: str) -> AuthFlow:
        provider = self.providers.get(provider_id)
        if provider is None:
            raise AuthError(f"Geen login-mogelijkheid voor {provider_id!r}.")
        return provider.start_flow(base_url)

    def complete_flow(self, provider_id: str, state: str) -> AuthLink:
        provider = self.providers.get(provider_id)
        if provider is None:
            raise AuthError(f"Geen login-mogelijkheid voor {provider_id!r}.")
        link = provider.complete_flow(state)
        self.link(link)
        return link
