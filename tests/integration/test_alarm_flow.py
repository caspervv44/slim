"""Integratie: alarmcyclus met button + agenda tot display (prototype)."""

from datetime import datetime, timedelta, timezone

from wekker.agenda.cache import AgendaCache
from wekker.agenda.providers import MockAgendaProvider
from wekker.agenda.sync import AgendaSyncService
from wekker.alarm.core import AlarmClock
from wekker.alarm.state import AlarmState
from wekker.button.controller import ButtonController
from wekker.clock import FakeClock
from wekker.display.manager import DisplayManager
from wekker.hardware.mock import (
    MockButton,
    MockDisplay,
    MockLamp,
    MockSpeaker,
)
from wekker.settings import default_settings


def _systeem(start: datetime):
    s = default_settings()
    s.alarm.time = "07:30"
    s.alarm.snooze_minutes = 5
    s.lamp.duration_after_button = 30
    klok = FakeClock(start)
    speaker, lamp = MockSpeaker(), MockLamp()
    driver = MockDisplay()
    core = AlarmClock(s, klok, speaker, lamp)
    cache = AgendaCache()
    display = DisplayManager(driver, s, klok, cache)
    controller = ButtonController(core, lamp, display, klok, s)
    knop = MockButton()
    knop.on_press(controller.press)
    knop.on_press(display.button_pressed)
    return s, klok, core, speaker, lamp, driver, display, controller, knop


def test_volledige_alarmcyclus_met_button():
    dag = datetime(2026, 9, 17, 7, 0, tzinfo=timezone.utc)
    s, klok, core, speaker, lamp, driver, display, controller, knop = _systeem(dag)

    # 1. alarm ingesteld, nog niet afgegaan
    assert core.state is AlarmState.SLEEPING

    # 2. wektijd bereikt -> actief met geluid en lamp
    klok.set(datetime(2026, 9, 17, 7, 30, tzinfo=timezone.utc))
    assert core.tick() is AlarmState.RINGING
    assert speaker.is_playing and lamp.is_on

    # 3. snooze
    assert core.snooze() is True
    assert core.state is AlarmState.SNOOZED

    # 4. na snooze opnieuw actief
    klok.advance(timedelta(minutes=5))
    assert core.tick() is AlarmState.RINGING

    # 5. button stopt het alarm en dooft de lamp
    knop.press()
    assert core.state is AlarmState.DISMISSED
    assert not speaker.is_playing and not lamp.is_on


def test_button_lamptimer_na_dismiss():
    dag = datetime(2026, 9, 17, 7, 30, tzinfo=timezone.utc)
    s, klok, core, speaker, lamp, driver, display, controller, knop = _systeem(dag)
    core.tick()
    knop.press()  # dismiss
    assert core.state is AlarmState.DISMISSED
    klok.advance(timedelta(seconds=1))  # debounce voorbij
    knop.press()  # geen alarm: lamp tijdelijk aan
    assert lamp.is_on
    for _ in range(30):
        klok.advance(timedelta(seconds=1))
        core.tick()
        display.tick()
        controller.tick()
    assert not lamp.is_on  # automatisch uit


def test_agenda_tot_display():
    klok = FakeClock(datetime(2026, 9, 14, 7, 0, tzinfo=timezone.utc))
    cache = AgendaCache()
    sync = AgendaSyncService(MockAgendaProvider(), cache, klok)
    assert sync.sync_today() is True
    driver = MockDisplay()
    mgr = DisplayManager(driver, default_settings(), klok, cache)
    mgr.button_pressed()
    assert "Wiskunde" in driver.text
    assert "08:30" in driver.text
