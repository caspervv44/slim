"""Lokale simulatiemodus: echte wekkerlogica met bestuurbare tijd.

Eerste prototype: display + speaker + lamp + één button. Bewegingshardware
is uitgesteld en wordt niet gesimuleerd.

Ontwerpprincipe: GEEN tweede wekkerlogica. ``Simulation`` gebruikt dezelfde
``AlarmClock``, ``ButtonController``, ``DisplayManager``,
``AgendaSyncService`` en instellingen als de echte applicatie; alleen de
klok (``FakeClock``) en de hardware (mocks) zijn verwisselbaar. Wat hier
werkt, werkt daarom ook op de Pi — minus de echte drivers.

Tijd loopt uitsluitend via ``advance(seconden)`` (seconde per seconde, zonder
``sleep``), met exact dezelfde tick-semantiek als de 1 Hz-weklus op de Pi
(zie ``main.run_once``).
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta

from wekker.agenda.cache import AgendaCache
from wekker.agenda.providers import MockAgendaProvider
from wekker.agenda.sync import AgendaSyncService
from wekker.alarm.core import AlarmClock
from wekker.alarm.state import AlarmState
from wekker.button.controller import ButtonController
from wekker.clock import FakeClock
from wekker.display.manager import DisplayManager
from wekker.hardware.mock import MockButton, MockDisplay, MockLamp, MockSpeaker
from wekker.settings import SettingsError, default_settings

#: Deterministische dem datum (donderdag → mockrooster met 4 lessen).
DEMO_DATE = "2026-09-17"

#: Bovengrens per advance-aanroep: een etmaal simuleren kan, meer niet.
MAX_ADVANCE_SECONDS = 86_400


@dataclass
class SimOptions:
    start: str = "07:29:50"  # HH:MM:SS
    day: str = DEMO_DATE  # YYYY-MM-DD
    alarm: str = "07:30"  # HH:MM
    snooze_minutes: int = 5
    lamp_duration_after_button: int = 30


def _parse_hms(value: str) -> dtime:
    try:
        parts = [int(p) for p in value.split(":")]
        return dtime(*parts)
    except (TypeError, ValueError) as exc:
        raise SettingsError(f"Starttijd moet HH:MM[:SS] zijn, kreeg {value!r}") from exc


def _parse_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SettingsError(f"Datum moet YYYY-MM-DD zijn, kreeg {value!r}") from exc


class Simulation:
    """Eén bestuurbare wekker: echte core/services, nep-tijd en nep-hardware."""

    def __init__(self, opts: SimOptions | None = None) -> None:
        self.opts = opts or SimOptions()
        tz = datetime.now().astimezone().tzinfo
        start = datetime.combine(
            _parse_day(self.opts.day), _parse_hms(self.opts.start)
        ).replace(tzinfo=tz)

        settings = default_settings().update_from_dict(
            {
                "alarm": {
                    "time": self.opts.alarm,
                    "snooze_minutes": self.opts.snooze_minutes,
                },
                "lamp": {
                    "duration_after_button": self.opts.lamp_duration_after_button,
                },
            }
        )
        self.settings = settings
        self.clock = FakeClock(start)
        self.speaker = MockSpeaker()
        self.lamp = MockLamp()
        self.driver = MockDisplay()
        self.button = MockButton()
        self.events: list[str] = []
        self.core = AlarmClock(
            settings, self.clock, self.speaker, self.lamp,
            on_state_change=self._record_and_wake,
        )
        self.cache = AgendaCache()
        self.display = DisplayManager(self.driver, settings, self.clock, self.cache)
        self.sync = AgendaSyncService(MockAgendaProvider(), self.cache, self.clock)
        self.controller = ButtonController(self.core, self.lamp, self.display,
                                           self.clock, settings)
        # Eén fysieke button: eerst de controller (zet o.a. de melding),
        # daarna het display wekken zodat alles in één keer gerenderd wordt.
        self.button.on_press(self.controller.press)
        self.button.on_press(self.display.button_pressed)

    # -- tijd -----------------------------------------------------------
    def advance(self, seconds: int) -> str:
        """Zet de gesimuleerde tijd vooruit (zelfde semantiek als de 1 Hz-lus)."""
        if not isinstance(seconds, int) or isinstance(seconds, bool):
            raise SettingsError(f"advance verwacht hele seconden, kreeg {seconds!r}")
        if not 0 <= seconds <= MAX_ADVANCE_SECONDS:
            raise SettingsError(f"advance moet 0..{MAX_ADVANCE_SECONDS} zijn")
        for _ in range(seconds):
            self.clock.advance(timedelta(seconds=1))
            try:
                self.core.tick()
            except Exception as exc:
                # Zelfde filosofie als main.run_once: loggen en doorgaan.
                self.events.append(f"{self.stamp()} FOUT core.tick: {exc!r}")
            try:
                self.display.tick()
            except Exception as exc:
                self.events.append(f"{self.stamp()} FOUT display.tick: {exc!r}")
            try:
                self.controller.tick()
            except Exception as exc:
                self.events.append(f"{self.stamp()} FOUT button.tick: {exc!r}")
            self._update_display_context()
        return f"+{seconds}s -> {self.stamp()} {self.core.state.value}"

    def stamp(self) -> str:
        return self.clock.now().strftime("%H:%M:%S")

    def _update_display_context(self) -> None:
        nxt = self.core.next_alarm()
        self.display.set_alarm_context(
            self.core.state.value,
            nxt.strftime("%H:%M") if nxt else None,
        )

    # -- acties (geven telkens een leesbare regel terug voor de CLI) -----
    def snooze(self) -> str:
        ok = self.core.snooze()
        self._update_display_context()
        return f"snooze: {'ok' if ok else 'geweigerd'} ({self.core.state.value})"

    def press_button(self) -> str:
        self.button.press()
        self._update_display_context()
        return f"button -> {self.core.state.value} (lamp: {'aan' if self.lamp.is_on else 'uit'})"

    def dismiss(self) -> str:
        ok = self.core.dismiss(physical=True)
        self._update_display_context()
        return f"dismiss: {'ok' if ok else 'geweigerd'} ({self.core.state.value})"

    def trigger(self) -> str:
        ok = self.core.trigger()
        self._update_display_context()
        return f"trigger: {'ok' if ok else 'geweigerd'} ({self.core.state.value})"

    def lamp_on(self) -> str:
        return self.controller.lamp_on()

    def lamp_off(self) -> str:
        return self.controller.lamp_off()

    def sync_agenda(self) -> str:
        ok = self.sync.sync_today()
        lessen = self.cache.get_day(self.clock.now().date())
        return f"agenda-sync: {'ok' if ok else 'mislukt'} ({len(lessen)} lessen)"

    def set_alarm(self, value: str) -> str:
        self._apply({"alarm": {"time": value}})
        return f"alarmtijd: {self.settings.alarm.time}"

    def set_snooze(self, minutes: int) -> str:
        self._apply({"alarm": {"snooze_minutes": minutes}})
        return f"snooze: {self.settings.alarm.snooze_minutes} min"

    def set_lampdur(self, seconds: int) -> str:
        self._apply({"lamp": {"duration_after_button": seconds}})
        return f"lampduur: {self.settings.lamp.duration_after_button}s"

    def _apply(self, patch: dict) -> None:
        nieuwe = self.settings.update_from_dict(patch)
        self.settings = nieuwe
        self.core.update_settings(nieuwe)
        self.display.update_settings(nieuwe)
        self.controller.update_settings(nieuwe)

    def _record(self, old: AlarmState, new: AlarmState) -> None:
        self.events.append(f"{self.stamp()} {old.value} -> {new.value}")

    def _record_and_wake(self, old: AlarmState, new: AlarmState) -> None:
        self._record(old, new)
        if new is AlarmState.RINGING:
            # Alarm gaat af: display aanzetten zodat de status zichtbaar is.
            self.display.button_pressed()

    # -- weergave --------------------------------------------------------
    def _refresh_if_visible(self) -> None:
        # Drivertekst kan achterlopen (gerenderd vóór de laatste context- of
        # meldingwijziging); zichtbaar display eerst vers renderen.
        if self.display.visible:
            self.display.refresh()

    def _agenda_regel(self) -> str:
        if self.cache.status == "never":
            return "niet gesynchroniseerd (stale)"
        lessen = self.cache.get_day(self.clock.now().date())
        vers = "" if not self.cache.is_stale(self.clock.now()) else " [STALE]"
        return f"{self.cache.status}, {len(lessen)} lessen{vers}"

    def status_text(self) -> str:
        self._refresh_if_visible()
        nxt = self.core.next_alarm()
        display = self.driver.text.replace("\n", " | ") if self.driver.text else "(uit)"
        lamp = "uit"
        if self.lamp.is_on:
            lamp = "aan (timer)" if self.controller.lamp_timer_active else "aan"
        speaker = f"aan ({self.speaker.current_sound})" if self.speaker.is_playing else "uit"
        return (
            f"Time: {self.stamp()}\n"
            f"State: {self.core.state.value}\n"
            f"Next alarm: {nxt.strftime('%H:%M:%S') if nxt else 'uit'}\n"
            f"Display: {display}\n"
            f"Speaker: {speaker}\n"
            f"Lamp: {lamp}\n"
            f"Agenda: {self._agenda_regel()}\n"
            f"Events: {len(self.events)}"
        )

    def display_text(self) -> str:
        self._refresh_if_visible()
        if not self.driver.text:
            return "(display uit - druk op de button)"
        rand = "+" + "-" * 28 + "+"
        body = "\n".join(f"| {r[:26]:26} |" for r in self.driver.text.split("\n"))
        return f"{rand}\n{body}\n{rand}"

    def log_text(self, last: int = 10) -> str:
        if not self.events:
            return "(geen events)"
        return "\n".join(self.events[-last:])


HELP = """Commando's:
  status            volledige wekkerstatus
  display           toon displayinhoud
  advance <sec>     tijd vooruit (0..86400), bv. advance 10
  snooze            snooze (alleen bij ringing)
  button            fysieke button indrukken
  dismiss           alarm afhandelen (als button)
  trigger           handmatig alarm starten (test)
  lamp on|off       lamp direct aan/uit
  sync              agenda synchroniseren
  alarm <HH:MM>     wektijd wijzigen, bv. alarm 07:45
  snoozemin <n>     snoozeduur wijzigen
  lampdur <n>       lampseconden na button wijzigen
  log [n]           laatste events tonen
  demo              alarmcyclus + lamptimer afspelen
  help              deze hulp
  quit              afsluiten"""

_QUIT = object()


def run_command(sim: Simulation, line: str) -> str | object:
    """Voer één CLI-regel uit. Geeft _QUIT bij quit, anders de uitvoertekst."""
    try:
        argv = shlex.split(line)
    except ValueError as exc:
        return f"fout: {exc}"
    if not argv:
        return ""
    cmd, args = argv[0].lower(), argv[1:]
    try:
        if cmd == "status":
            return sim.status_text()
        if cmd == "display":
            return sim.display_text()
        if cmd == "advance":
            if len(args) != 1:
                return "gebruik: advance <seconden>"
            return sim.advance(int(args[0]))
        if cmd == "snooze":
            return sim.snooze()
        if cmd == "button":
            return sim.press_button()
        if cmd == "dismiss":
            return sim.dismiss()
        if cmd == "trigger":
            return sim.trigger()
        if cmd == "lamp":
            if args == ["on"]:
                return sim.lamp_on()
            if args == ["off"]:
                return sim.lamp_off()
            return "gebruik: lamp on|off"
        if cmd == "sync":
            return sim.sync_agenda()
        if cmd == "alarm":
            if len(args) != 1:
                return "gebruik: alarm <HH:MM>"
            return sim.set_alarm(args[0])
        if cmd == "snoozemin":
            if len(args) != 1:
                return "gebruik: snoozemin <minuten>"
            return sim.set_snooze(int(args[0]))
        if cmd == "lampdur":
            if len(args) != 1:
                return "gebruik: lampdur <seconden>"
            return sim.set_lampdur(int(args[0]))
        if cmd == "log":
            n = int(args[0]) if args else 10
            return sim.log_text(n)
        if cmd == "demo":
            return demo_transcript(sim)
        if cmd in ("help", "?"):
            return HELP
        if cmd in ("quit", "exit", "q"):
            return _QUIT
    except (ValueError, SettingsError) as exc:
        return f"fout: {exc}"
    return f"onbekend commando: {cmd} (typ 'help')"


def demo_transcript(sim: Simulation) -> str:
    """Scripted cyclus voor het eerste prototype: alarm → button-dismiss
    en lamp-timer (aan → automatisch uit). Gebruikt door de CLI én controles."""
    stappen: list[str] = [
        "status",
        "sync",
        "advance 10",  # 07:29:50 -> 07:30:00: alarm gaat af
        "display",  # toont ALARM!
        "button",  # alarm afgehandeld via de button
        "status",
        "advance 1",  # debounce-venster voorbij
        "button",  # geen alarm actief: lamp tijdelijk aan
        "display",  # toont lamp-melding
        "advance 30",  # lamp gaat automatisch uit
        "status",
    ]
    uit: list[str] = []
    for stap in stappen:
        resultaat = run_command(sim, stap)
        assert resultaat is not _QUIT
        uit.append(f"> {stap}\n{resultaat}")
    return "\n\n".join(uit)


def repl(sim: Simulation) -> int:
    """Interactieve simulatie-REPL. Geeft exitcode terug."""
    print("Wekker-simulatie (nep-tijd, echte core). Typ 'help', 'demo' of 'quit'.")
    print(sim.status_text())
    fouten = 0
    while True:
        try:
            regel = input("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        resultaat = run_command(sim, regel)
        if resultaat is _QUIT:
            break
        if resultaat:
            print(resultaat)
            if isinstance(resultaat, str) and resultaat.startswith(("fout:", "onbekend")):
                fouten += 1
    return 1 if fouten else 0


def run_script(sim: Simulation, script: str) -> int:
    """Voer puntkomma/regel-gescheiden commando's niet-interactief uit."""
    fouten = 0
    regels = [r.strip() for r in script.replace(";", "\n").split("\n")]
    for regel in regels:
        if not regel:
            continue
        print(f"> {regel}")
        resultaat = run_command(sim, regel)
        if resultaat is _QUIT:
            break
        print(resultaat)
        if isinstance(resultaat, str) and resultaat.startswith(("fout:", "onbekend")):
            fouten += 1
    return 1 if fouten else 0
