"""Centrale wekkerlogica als expliciete state machine.

Toestanden eerste prototype: SLEEPING -> RINGING -> DISMISSED, met optionele
snooze (RINGING -> SNOOZED -> RINGING). Bewegingshardware is uitgesteld naar
een latere prototypefase en maakt geen deel uit van deze versie.

De core kent geen GPIO: alle bijwerkingen lopen via de hardware-Protocols.
Tijd komt binnen via een Clock (tests gebruiken FakeClock).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta

from wekker.alarm.state import AlarmState
from wekker.clock import Clock
from wekker.hardware.interfaces import Lamp, Speaker
from wekker.settings import Settings

log = logging.getLogger(__name__)

_ALLOWED: dict[AlarmState, frozenset[AlarmState]] = {
    AlarmState.SLEEPING: frozenset({AlarmState.RINGING}),
    AlarmState.RINGING: frozenset({AlarmState.SNOOZED, AlarmState.DISMISSED}),
    AlarmState.SNOOZED: frozenset({AlarmState.RINGING, AlarmState.DISMISSED}),
    AlarmState.DISMISSED: frozenset({AlarmState.SLEEPING}),
}


class IllegalTransitionError(Exception):
    """Poging tot een niet-toegestane toestandsovergang."""


class AlarmClock:
    """Betrouwbare wekker-core zonder hardware-afhankelijkheid."""

    def __init__(
        self,
        settings: Settings,
        clock: Clock,
        speaker: Speaker,
        lamp: Lamp,
        on_state_change: Callable[[AlarmState, AlarmState], None] | None = None,
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._speaker = speaker
        self._lamp = lamp
        self._on_state_change = on_state_change
        # RLock: de setup-API draait in een aparte thread en echte
        # GPIO-callbacks komen later op eigen threads binnen. De lock maakt
        # tick()/snooze()/dismiss() onderling atomaire. Let op: de
        # on_state_change-callback draait ONDER deze lock en mag daarom geen
        # core-methoden aanroepen (RLock vangt dat binnen één thread wel op,
        # maar houd de callback snel en zonder bijwerkingen op de core).
        self._lock = threading.RLock()
        self.state: AlarmState = AlarmState.SLEEPING
        self.ringing_since: datetime | None = None
        self.snooze_until: datetime | None = None
        self._last_trigger_date: str | None = None
        self._dismissed_date: str | None = None

    # -- configuratie ----------------------------------------------------
    def update_settings(self, settings: Settings) -> None:
        with self._lock:
            self._settings = settings

    @property
    def speaker_playing(self) -> bool:
        """True als het alarmgeluid actief is."""
        with self._lock:
            return self._speaker.is_playing

    def sound_start(self) -> None:
        """Start het ingestelde geluid (voor de setup-app testfunctie)."""
        with self._lock:
            alarm = self._settings.alarm
            self._speaker.play(alarm.sound, alarm.volume)

    def sound_stop(self) -> None:
        """Stop het geluid (voor de setup-app testfunctie)."""
        with self._lock:
            self._speaker.stop()

    # -- publieke acties -------------------------------------------------
    def trigger(self) -> bool:
        """Activeer het alarm handmatig (alleen vanuit SLEEPING)."""
        with self._lock:
            if self.state is not AlarmState.SLEEPING:
                return False
            self._transition(AlarmState.RINGING)
            return True

    def snooze(self) -> bool:
        """Stel het alarm uit. Alleen vanuit RINGING."""
        with self._lock:
            if self.state is not AlarmState.RINGING:
                return False
            now = self._clock.now()
            minutes = self._settings.alarm.snooze_minutes
            # Pas ná succesvolle transitie vastleggen (zie _transition):
            # bij een hardwarefout blijft de oude situatie herstelbaar.
            self._transition(AlarmState.SNOOZED)
            self.snooze_until = now + timedelta(minutes=minutes)
            return True

    def dismiss(self, physical: bool) -> bool:
        """Stop het alarm. Vereist een fysieke bevestiging (de button).

        Zo voorkomen we dat het alarm per ongeluk op afstand stilgezet wordt
        terwijl de gebruiker in bed blijft liggen. De button-controller roept
        dit aan met physical=True.
        """
        with self._lock:
            if self.state not in (AlarmState.RINGING, AlarmState.SNOOZED):
                return False
            if not physical:
                log.warning("dismiss geweigerd: geen fysieke bevestiging")
                return False
            self._transition(AlarmState.DISMISSED)
            return True

    def tick(self) -> AlarmState:
        """Werk de toestand bij aan de hand van de klok. Idempotent.

        Gooit hardwarefouten door naar de aanroeper (de wekkerlus vangt ze
        op en probeert het de volgende seconde opnieuw); de toestand blijft
        bij een fout consistent, zie _transition.
        """
        with self._lock:
            now = self._clock.now()
            today = now.date().isoformat()

            if self.state is AlarmState.SLEEPING:
                if self._settings.alarm.enabled and self._due_today(now):
                    self._transition(AlarmState.RINGING)
                    # Pas ná succes markeren: bij een hardwarefout halverwege
                    # mag het alarm vandaag opnieuw proberen i.p.v. verloren gaan.
                    self._last_trigger_date = today
            elif self.state is AlarmState.SNOOZED:
                if self.snooze_until is not None and now >= self.snooze_until:
                    self._transition(AlarmState.RINGING)
                    self.snooze_until = None
            elif self.state is AlarmState.DISMISSED:
                if self._dismissed_date != today:
                    # Nieuwe dag: weer klaar voor het volgende alarm.
                    self._transition(AlarmState.SLEEPING)
            return self.state

    def next_alarm(self, now: datetime | None = None) -> datetime | None:
        """Volgende wektijd, of None als het alarm uit staat.

        Tijdens SNOOZED is dat het einde van de snooze (de eerstvolgende keer
        dat het alarm afgaat), niet de wektijd van morgen.
        """
        with self._lock:
            if not self._settings.alarm.enabled:
                return None
            if self.state is AlarmState.SNOOZED and self.snooze_until is not None:
                return self.snooze_until
            ref = now or self._clock.now()
            uur, minuut = map(int, self._settings.alarm.time.split(":"))
            kandidaat = ref.replace(hour=uur, minute=minuut, second=0, microsecond=0)
            if kandidaat <= ref:
                kandidaat += timedelta(days=1)
            return kandidaat

    def status(self) -> dict:
        with self._lock:
            now = self._clock.now()
            nxt = self.next_alarm(now)
            return {
                "state": self.state.value,
                "now": now.isoformat(),
                "next_alarm": nxt.isoformat() if nxt else None,
                "ringing_since": self.ringing_since.isoformat() if self.ringing_since else None,
                "snooze_until": self.snooze_until.isoformat() if self.snooze_until else None,
            }

    # -- intern ----------------------------------------------------------
    def _due_today(self, now: datetime) -> bool:
        if self._last_trigger_date == now.date().isoformat():
            return False  # vandaag al afgegaan
        uur, minuut = map(int, self._settings.alarm.time.split(":"))
        trigger = now.replace(hour=uur, minute=minuut, second=0, microsecond=0)
        # 60 seconden venster: tick() draait ~1x per seconde.
        return trigger <= now < trigger + timedelta(seconds=60)

    def _transition(self, new: AlarmState) -> None:
        if new not in _ALLOWED[self.state]:
            raise IllegalTransitionError(f"{self.state.value} -> {new.value} niet toegestaan")
        old = self.state
        # Eerst de hardware, dan pas de toestand vastleggen. Faalt een driver
        # (defecte speaker/lamp op de Pi), dan blijft de oude toestand staan
        # en probeert tick() het later opnieuw — in plaats van een "stil
        # alarm" waarbij de toestand RINGING zegt maar niets rinkelt.
        # Aanroepen lopen onder de RLock; houd _enter vrij van callbacks
        # terug de core in.
        self._enter(new)
        self.state = new
        log.info("alarm %s -> %s", old.value, new.value)
        if self._on_state_change:
            self._on_state_change(old, new)

    def _enter(self, state: AlarmState) -> None:
        now = self._clock.now()
        alarm = self._settings.alarm
        lamp_cfg = self._settings.lamp
        if state is AlarmState.RINGING:
            if self.ringing_since is None:
                self.ringing_since = now
            if alarm.speaker_enabled:
                self._speaker.play(alarm.sound, alarm.volume)
            if lamp_cfg.on_with_alarm:
                self._lamp.on(
                    alarm.lamp_brightness,
                    blink=alarm.lamp_blink,
                    pattern=alarm.blink_pattern,
                )
        elif state is AlarmState.SNOOZED:
            self._speaker.stop()
            self._lamp.off()
        elif state is AlarmState.DISMISSED:
            self._dismissed_date = now.date().isoformat()
            self.snooze_until = None
            self.ringing_since = None
            self._speaker.stop()
            self._lamp.off()
        elif state is AlarmState.SLEEPING:
            self.ringing_since = None
            self.snooze_until = None
            self._speaker.stop()
            self._lamp.off()
