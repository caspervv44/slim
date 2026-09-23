"""Synchronisatieservice: provider -> cache, met nette foutafhandeling."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta

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

    def _mark_error(self, message: str) -> None:
        self._cache.mark_error(self._clock.now(), message)

    def sync_day(self, day: date) -> bool:
        """Synchroniseer één dag. Geeft True bij succes, False bij fout."""
        try:
            lessen = self._provider.fetch_day(day)
        except ProviderError as exc:
            log.warning("agenda-sync mislukt voor %s: %s", day.isoformat(), exc)
            self._mark_error(str(exc))
            return False
        except Exception as exc:  # onverwachte adapterfout: cache behouden
            log.exception("onverwachte agenda-fout voor %s", day.isoformat())
            self._mark_error(f"{type(exc).__name__}: {exc}")
            return False

        self._cache.put_day(day, lessen)
        self._cache.mark_ok(self._clock.now())
        log.info("agenda-sync ok voor %s (%d lessen)", day.isoformat(), len(lessen))
        return True

    def sync_range(self, start: date, end_exclusive: date) -> bool:
        """Synchroniseer een half-open datumbereik atomair richting de cache.

        Providers met ``fetch_range`` (zoals MyX) halen de hele periode in één
        request op. Oudere providers blijven compatibel via ``fetch_day``.
        Bij een fout wordt géén deel van de bestaande cache overschreven.
        """
        if end_exclusive <= start:
            raise ValueError("end_exclusive moet na start liggen")

        try:
            fetch_range = getattr(self._provider, "fetch_range", None)
            if callable(fetch_range):
                lessen = list(fetch_range(start, end_exclusive))
            else:
                lessen = []
                dag = start
                while dag < end_exclusive:
                    lessen.extend(self._provider.fetch_day(dag))
                    dag += timedelta(days=1)
        except ProviderError as exc:
            log.warning(
                "agenda-sync mislukt voor %s..%s: %s",
                start.isoformat(),
                end_exclusive.isoformat(),
                exc,
            )
            self._mark_error(str(exc))
            return False
        except Exception as exc:
            log.exception(
                "onverwachte agenda-fout voor %s..%s",
                start.isoformat(),
                end_exclusive.isoformat(),
            )
            self._mark_error(f"{type(exc).__name__}: {exc}")
            return False

        per_dag = defaultdict(list)
        for les in lessen:
            per_dag[les.start.date()].append(les)

        dag = start
        while dag < end_exclusive:
            self._cache.put_day(dag, per_dag.get(dag, []))
            dag += timedelta(days=1)

        self._cache.mark_ok(self._clock.now())
        log.info(
            "agenda-sync ok voor %s..%s (%d lessen)",
            start.isoformat(),
            end_exclusive.isoformat(),
            len(lessen),
        )
        return True

    def sync_today(self) -> bool:
        return self.sync_day(self._clock.now().date())

    def sync_default_window(self) -> bool:
        """Synchroniseer de door de provider gewenste horizon.

        Bestaande providers blijven op één dag. MyX kan een grotere periode in
        één InternetCalendar-request ophalen.
        """
        dagen = int(getattr(self._provider, "sync_horizon_days", 1))
        dagen = max(1, min(dagen, 60))
        vandaag = self._clock.now().date()
        if dagen == 1:
            return self.sync_day(vandaag)
        return self.sync_range(vandaag, vandaag + timedelta(days=dagen))
