"""Synchronisatieservice: provider -> cache, met nette foutafhandeling."""

from __future__ import annotations

import logging
from datetime import date

from wekker.agenda.cache import AgendaCache
from wekker.agenda.providers import AgendaProvider, ProviderError
from wekker.clock import Clock

log = logging.getLogger(__name__)


class AgendaSyncService:
    def __init__(self, provider: AgendaProvider, cache: AgendaCache, clock: Clock) -> None:
        self._provider = provider
        self._cache = cache
        self._clock = clock

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def sync_day(self, day: date) -> bool:
        """Synchroniseer één dag. Geeft True bij succes, False bij fout."""
        try:
            lessen = self._provider.fetch_day(day)
        except ProviderError as exc:
            log.warning("agenda-sync mislukt voor %s: %s", day.isoformat(), exc)
            self._cache.mark_error(self._clock.now(), str(exc))
            return False
        except Exception as exc:  # onverwachte adapterfout: cache behouden
            log.exception("onverwachte agenda-fout voor %s", day.isoformat())
            self._cache.mark_error(self._clock.now(), f"{type(exc).__name__}: {exc}")
            return False
        self._cache.put_day(day, lessen)
        self._cache.mark_ok(self._clock.now())
        log.info("agenda-sync ok voor %s (%d lessen)", day.isoformat(), len(lessen))
        return True

    def sync_today(self) -> bool:
        return self.sync_day(self._clock.now().date())
