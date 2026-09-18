"""DisplayManager: bouwt het schermmodel, onafhankelijk van het schermtype.

Stroom: ``AgendaCache`` -> ``DisplayManager.render()`` -> ``DisplayDriver``.
Voor de laptop is de driver een MockDisplay; op de Pi een LED-driver met
dezelfde drie methoden (show/clear/set_brightness).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import threading

from wekker.agenda.cache import AgendaCache
from wekker.clock import Clock
from wekker.hardware.interfaces import DisplayDriver
from wekker.settings import Settings


@dataclass
class ScreenModel:
    lines: list[str]
    dimmed: bool = False


class DisplayManager:
    """Beheert wat er zichtbaar is, hoelang, en hoe fel."""

    def __init__(
        self,
        driver: DisplayDriver,
        settings: Settings,
        clock: Clock,
        agenda: AgendaCache,
    ) -> None:
        self._driver = driver
        self._settings = settings
        self._clock = clock
        self._agenda = agenda
        self._on_until: datetime | None = None
        self.visible: bool = False
        # Context van buiten: alarmtoestand + volgende wektijd (gezet door de
        # wekkerlus) en een korte melding (gezet door de button-controller).
        self._alarm_state: str | None = None
        self._next_alarm: str | None = None
        self._notice: str | None = None
        # RLock: button_pressed() komt via de API-thread en straks via
        # GPIO-callback-threads binnen, terwijl tick() op de wekkerlus loopt.
        self._lock = threading.RLock()

    def update_settings(self, settings: Settings) -> None:
        with self._lock:
            self._settings = settings

    def set_alarm_context(self, alarm_state: str | None, next_alarm: str | None) -> None:
        """Werk alarmstatus + volgende wektijd bij (aangeroepen door wekkerlus)."""
        with self._lock:
            self._alarm_state = alarm_state
            self._next_alarm = next_alarm

    def set_notice(self, text: str) -> None:
        """Toon een korte melding (bv. 'Lamp aan'), tot clear_notice()."""
        with self._lock:
            self._notice = text

    def clear_notice(self) -> None:
        with self._lock:
            self._notice = None

    # -- events ---------------------------------------------------------
    def button_pressed(self) -> None:
        """Knopdrukt: zet het display aan voor de ingestelde duur."""
        with self._lock:
            now = self._clock.now()
            seconds = self._settings.display.on_duration_seconds
            self._on_until = now + timedelta(seconds=seconds)
            self.refresh_locked()

    def tick(self) -> None:
        """Periodiek aanroepen (1x/sec): auto-uit + nachtmodus."""
        with self._lock:
            now = self._clock.now()
            if self._on_until is not None and now >= self._on_until:
                self._on_until = None
                self._driver.clear()
                self.visible = False
                return
            if self._on_until is not None:
                self.refresh_locked()

    # -- render ----------------------------------------------------------
    def render(self, now: datetime | None = None) -> ScreenModel:
        with self._lock:
            now = now or self._clock.now()
            fields = self._settings.display.visible_fields
            lessen = self._agenda.get_day(now.date())
            lines: list[str] = []
            if "time" in fields:
                lines.append(now.strftime("%H:%M"))
            if self._alarm_state == "ringing":
                lines.append("ALARM!")
            elif self._alarm_state == "snoozed":
                lines.append("Snooze...")
            if "next_alarm" in fields and self._next_alarm:
                lines.append(f"Alarm: {self._next_alarm}")
            if lessen:
                eerste, laatste = lessen[0], lessen[-1]
                if "first_lesson" in fields:
                    lines.append(f"1e: {eerste.subject} {eerste.start.strftime('%H:%M')}")
                if "teacher" in fields:
                    lines.append(f"Docent: {eerste.teacher}")
                if "room" in fields:
                    lines.append(f"Lokaal: {eerste.room}")
                if "last_lesson" in fields:
                    lines.append(f"Laatste: {laatste.subject} {laatste.end.strftime('%H:%M')}")
                if "day_agenda" in fields or "appointments" in fields:
                    for les in lessen:
                        lines.append(
                            f"{les.start.strftime('%H:%M')} {les.subject} ({les.room})"
                        )
            else:
                if "first_lesson" in fields:
                    lines.append("Geen lessen vandaag")
            if self._notice:
                lines.append(self._notice)
            return ScreenModel(lines=lines, dimmed=self._is_night(now))

    def refresh(self) -> ScreenModel:
        """Toon het huidige schermmodel op de driver."""
        with self._lock:
            return self.refresh_locked()

    def refresh_locked(self) -> ScreenModel:
        """Zelfde als refresh(), maar gaat uit van een vastgehouden lock."""
        now = self._clock.now()
        model = self.render(now)
        if self._is_night(now) and self._settings.display.night_mode == "off":
            self._driver.clear()
            self.visible = False
            return model
        brightness = self._settings.display.brightness
        if model.dimmed:
            brightness = min(brightness, 10)
        self._driver.set_brightness(brightness)
        self._driver.show(model.lines)
        self.visible = True
        return model

    def format_terminal(self, now: datetime | None = None) -> str:
        """Eenvoudige terminalweergave voor de laptop-demo."""
        model = self.render(now)
        rand = "+" + "-" * 28 + "+"
        body = "\n".join(f"| {r[:26]:26} |" for r in model.lines) or "| (leeg)                     |"
        suffix = " (gedimd)" if model.dimmed else ""
        return f"{rand}\n{body}\n{rand}{suffix}"

    # -- intern ----------------------------------------------------------
    def _is_night(self, now: datetime) -> bool:
        def mins(t: str) -> int:
            h, m = map(int, t.split(":"))
            return h * 60 + m

        cur = now.hour * 60 + now.minute
        start = mins(self._settings.display.night_start)
        end = mins(self._settings.display.night_end)
        if start <= end:
            return start <= cur < end
        return cur >= start or cur < end
