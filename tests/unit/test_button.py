"""Tests: button-controller — debounce, alarm-afhandeling, lamptimer."""

from datetime import datetime, timedelta, timezone

import pytest

from wekker.agenda.cache import AgendaCache
from wekker.alarm.core import AlarmClock
from wekker.alarm.state import AlarmState
from wekker.button.controller import ButtonController
from wekker.clock import FakeClock
from wekker.display.manager import DisplayManager
from wekker.hardware.mock import MockButton, MockDisplay, MockLamp, MockSpeaker
from wekker.settings import default_settings


def _bouw(start: datetime, duur: int = 30):
    s = default_settings()
    s.alarm.time = "07:30"
    s.lamp.duration_after_button = duur
    klok = FakeClock(start)
    speaker, lamp = MockSpeaker(), MockLamp()
    driver = MockDisplay()
    core = AlarmClock(s, klok, speaker, lamp)
    display = DisplayManager(driver, s, klok, AgendaCache())
    controller = ButtonController(core, lamp, display, klok, s)
    knop = MockButton()
    knop.on_press(controller.press)
    return s, klok, core, lamp, driver, display, controller, knop


def _ochtend():
    return datetime(2026, 9, 17, 6, 0, tzinfo=timezone.utc)


def test_druk_zonder_alarm_zet_lamp_tijdelijk_aan():
    _, klok, core, lamp, _, _, controller, _ = _bouw(_ochtend())
    assert controller.press() == "lamp-aan"
    assert lamp.is_on
    assert controller.lamp_timer_active is True
    assert core.state is AlarmState.SLEEPING  # wekkertoestand ongewijzigd
    klok.advance(timedelta(seconds=29))
    controller.tick()
    assert lamp.is_on
    klok.advance(timedelta(seconds=1))
    controller.tick()
    assert not lamp.is_on
    assert controller.lamp_timer_active is False


def test_tweede_druk_reset_timer():
    _, klok, _, lamp, _, _, controller, _ = _bouw(_ochtend(), duur=30)
    controller.press()
    klok.advance(timedelta(seconds=20))
    controller.tick()
    controller.press()  # opnieuw: timer begint opnieuw
    klok.advance(timedelta(seconds=20))
    controller.tick()
    assert lamp.is_on  # 20 s na tweede druk, niet 40 s na eerste
    klok.advance(timedelta(seconds=10))
    controller.tick()
    assert not lamp.is_on


def test_debounce_negeert_snearchtere_druk():
    _, klok, _, lamp, _, _, controller, knop = _bouw(_ochtend())
    knop.press()
    assert controller.accepted_presses == 1
    knop.press()  # zelfde milliseconde: prellen
    assert controller.accepted_presses == 1
    assert controller.ignored_presses == 1
    assert lamp.is_on  # slechts één keer aangezet
    klok.advance(timedelta(seconds=1))
    knop.press()  # bewuste tweede druk: telt wel
    assert controller.accepted_presses == 2


def test_druk_bij_actief_alarm_handelt_af():
    _, klok, core, lamp, _, _, controller, _ = _bouw(_ochtend())
    klok.set(datetime(2026, 9, 17, 7, 30, tzinfo=timezone.utc))
    core.tick()
    assert core.state is AlarmState.RINGING
    assert controller.press() == "alarm-gestopt"
    assert core.state is AlarmState.DISMISSED
    assert not lamp.is_on  # lamp uit bij afhandeling


def test_druk_bij_snooze_handelt_af():
    _, klok, core, _, _, _, controller, _ = _bouw(_ochtend())
    klok.set(datetime(2026, 9, 17, 7, 30, tzinfo=timezone.utc))
    core.tick()
    core.snooze()
    assert controller.press() == "alarm-gestopt"
    assert core.state is AlarmState.DISMISSED


def test_shutdown_zet_lamp_uit():
    _, _, _, lamp, _, _, controller, _ = _bouw(_ochtend())
    controller.press()
    assert lamp.is_on
    controller.shutdown()
    assert not lamp.is_on
    assert controller.lamp_timer_active is False


def test_directe_lampbediening():
    _, klok, _, lamp, _, _, controller, _ = _bouw(_ochtend())
    assert controller.lamp_on(5) == "lamp-aan (5s)"
    assert lamp.is_on
    klok.advance(timedelta(seconds=5))
    controller.tick()
    assert not lamp.is_on
    with pytest.raises(ValueError):
        controller.lamp_on(0)
    with pytest.raises(ValueError):
        controller.lamp_on("lang")  # type: ignore[arg-type]
    controller.lamp_on()
    assert controller.lamp_off() == "lamp-uit"
    assert not lamp.is_on


def test_nieuwe_instellingen_worden_toegepast():
    s, _, _, lamp, _, _, controller, _ = _bouw(_ochtend(), duur=30)
    nieuwe = s.update_from_dict({"lamp": {"duration_after_button": 60}})
    controller.update_settings(nieuwe)
    controller.press()
    assert controller._lamp_until is not None
    assert (controller._lamp_until - controller._clock.now()) == timedelta(seconds=60)
    assert lamp.is_on


def test_lampmelding_op_display():
    _, _, _, _, driver, display, controller, _ = _bouw(_ochtend())
    controller.press()
    display.button_pressed()  # display wekken zoals de echte button doet
    assert "Lamp aan (button)" in driver.text
    controller.tick()  # timer loopt nog: melding blijft
    display.refresh()
    assert "Lamp aan (button)" in driver.text
