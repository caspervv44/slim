"""Button-controller voor het eerste prototype (één button).

Gedocumenteerde werking, gekozen voor eenvoud:

- Alarm actief (RINGING/SNOOZED) + druk → alarm wordt afgehandeld
  (``dismiss`` met fysieke bevestiging), lamp gaat uit.
- Alarm niet actief + druk → lamp gaat aan voor
  ``lamp.duration_after_button`` seconden en daarna automatisch uit.
  Een nieuwe druk binnen die tijd start de timer opnieuw.
- Drukken binnen 0,3 s na de vorige druk worden genegeerd (debounce),
  zodat één fysieke druk nooit twee keer telt.
- Bij afsluiten gaat de lamp altijd uit (``shutdown``).

De controller is hardware-onafhankelijk: hij praat alleen met de core, de
lamp, het display en een klok. Echte GPIO-drivers hoeven alleen
``Button.on_press`` te implementeren; software-debounce zit hier, zodat ook
een prellende knop zich netjes gedraagt.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from wekker.alarm.core import AlarmClock
from wekker.alarm.state import AlarmState
from wekker.clock import Clock
from wekker.display.manager import DisplayManager
from wekker.hardware.interfaces import Lamp
from wekker.settings import Settings

log = logging.getLogger(__name__)

#: Drukken korter na elkaar dan dit worden genegeerd (prellen).
DEBOUNCE_SECONDS = 0.3

_ALARM_ACTIEF = frozenset({AlarmState.RINGING, AlarmState.SNOOZED})


class ButtonController:
    """Koppelt één button aan alarm-afhandeling en tijdelijke lamp."""

    def __init__(
        self,
        core: AlarmClock,
        lamp: Lamp,
        display: DisplayManager,
        clock: Clock,
        settings: Settings,
    ) -> None:
        self._core = core
        self._lamp = lamp
        self._display = display
        self._clock = clock
        self._settings = settings
        self._lock = threading.RLock()
        self._lamp_until: datetime | None = None
        self._last_press: datetime | None = None
        self.accepted_presses: int = 0
        self.ignored_presses: int = 0

    def update_settings(self, settings: Settings) -> None:
        with self._lock:
            self._settings = settings

    # -- events ---------------------------------------------------------
    def press(self) -> str:
        """Verwerk één buttondruk. Geeft terug wat er gebeurde."""
        with self._lock:
            now = self._clock.now()
            if self._last_press is not None:
                if (now - self._last_press).total_seconds() < DEBOUNCE_SECONDS:
                    self.ignored_presses += 1
                    return "genegeerd (debounce)"
            self._last_press = now
            self.accepted_presses += 1
            if self._core.state in _ALARM_ACTIEF:
                self._core.dismiss(physical=True)
                self._lamp_timer_stop_locked()
                log.info("button: alarm afgehandeld")
                return "alarm-gestopt"
            self.lamp_on_locked()
            log.info("button: lamp tijdelijk aan")
            return "lamp-aan"

    def tick(self) -> None:
        """Periodiek aanroepen (1x/sec): lamp-timer laten aflopen."""
        with self._lock:
            if self._lamp_until is not None and self._clock.now() >= self._lamp_until:
                self._lamp_timer_stop_locked()

    def shutdown(self) -> None:
        """Lamp veilig uit bij afsluiten van de applicatie."""
        with self._lock:
            self._lamp_timer_stop_locked()

    # -- directe lampbediening (setup-API) --------------------------------
    def lamp_on(self, duration_seconds: int | None = None) -> str:
        """Lamp aan, optioneel met eigen duur (default: instelling)."""
        with self._lock:
            if duration_seconds is None:
                duration_seconds = self._settings.lamp.duration_after_button
            if not isinstance(duration_seconds, int) or isinstance(duration_seconds, bool):
                raise ValueError("duration_seconds moet een geheel getal zijn")
            if not 1 <= duration_seconds <= 3600:
                raise ValueError("duration_seconds moet 1..3600 zijn")
            self._lamp.on(100, blink=False, pattern="steady")
            self._lamp_until = self._clock.now() + timedelta(seconds=duration_seconds)
            self._display.set_notice("Lamp aan")
            return f"lamp-aan ({duration_seconds}s)"

    def lamp_off(self) -> str:
        with self._lock:
            self._lamp_timer_stop_locked()
            return "lamp-uit"

    @property
    def lamp_timer_active(self) -> bool:
        with self._lock:
            return self._lamp_until is not None

    @property
    def lamp_is_on(self) -> bool:
        with self._lock:
            return self._lamp.is_on

    # -- intern ----------------------------------------------------------
    def lamp_on_locked(self) -> None:
        """Zelfde als lamp_on(), maar gaat uit van een vastgehouden lock."""
        self._lamp.on(100, blink=False, pattern="steady")
        seconds = self._settings.lamp.duration_after_button
        self._lamp_until = self._clock.now() + timedelta(seconds=seconds)
        self._display.set_notice("Lamp aan (button)")

    def _lamp_timer_stop_locked(self) -> None:
        self._lamp_until = None
        self._lamp.off()
        self._display.clear_notice()
