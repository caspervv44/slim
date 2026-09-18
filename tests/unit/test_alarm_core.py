"""Tests: wekker-core state machine (eerste prototype, zonder motor)."""

from datetime import datetime, timedelta, timezone

import pytest

from wekker.alarm.core import AlarmClock
from wekker.alarm.state import AlarmState
from wekker.clock import FakeClock
from wekker.hardware.mock import MockLamp, MockSpeaker
from wekker.settings import default_settings


def _bouw(start: datetime):
    s = default_settings()
    s.alarm.time = "07:30"
    s.alarm.snooze_minutes = 9
    klok = FakeClock(start)
    speaker, lamp = MockSpeaker(), MockLamp()
    core = AlarmClock(s, klok, speaker, lamp)
    return s, klok, core, speaker, lamp


def _ochtend():
    return datetime(2026, 9, 17, 6, 0, tzinfo=timezone.utc)


def test_alarm_gaat_af_op_wektijd():
    _, klok, core, speaker, lamp = _bouw(_ochtend())
    klok.set(datetime(2026, 9, 17, 7, 30, tzinfo=timezone.utc))
    assert core.tick() is AlarmState.RINGING
    assert speaker.is_playing
    assert lamp.is_on


def test_speaker_en_lamp_uitschakelbaar_via_instellingen():
    s, klok, core, speaker, lamp = _bouw(_ochtend())
    s.alarm.speaker_enabled = False
    s.lamp.on_with_alarm = False
    klok.set(datetime(2026, 9, 17, 7, 30, tzinfo=timezone.utc))
    assert core.tick() is AlarmState.RINGING
    assert not speaker.is_playing
    assert not lamp.is_on


def test_geen_dubbele_trigger_zelfde_dag():
    _, klok, core, _, _ = _bouw(_ochtend())
    klok.set(datetime(2026, 9, 17, 7, 30, tzinfo=timezone.utc))
    core.tick()
    assert core.dismiss(physical=True) is True
    assert core.state is AlarmState.DISMISSED
    klok.set(datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc))
    core.tick()  # DISMISSED blijft (zelfde dag)
    klok.set(datetime(2026, 9, 18, 7, 30, tzinfo=timezone.utc))
    core.tick()  # nieuwe dag: DISMISSED -> SLEEPING
    assert core.state is AlarmState.SLEEPING
    core.tick()
    assert core.state is AlarmState.RINGING


def test_snooze_en_opnieuw_rinkelen():
    _, klok, core, speaker, _ = _bouw(_ochtend())
    klok.set(datetime(2026, 9, 17, 7, 30, tzinfo=timezone.utc))
    core.tick()
    assert core.snooze() is True
    assert core.state is AlarmState.SNOOZED
    assert not speaker.is_playing
    klok.advance(timedelta(minutes=8, seconds=59))
    core.tick()
    assert core.state is AlarmState.SNOOZED
    klok.advance(timedelta(seconds=1))
    assert core.tick() is AlarmState.RINGING


def test_snooze_alleen_vanuit_ringing():
    _, _, core, _, _ = _bouw(_ochtend())
    assert core.snooze() is False  # SLEEPING
    assert core.trigger() is True
    assert core.snooze() is True
    assert core.snooze() is False  # al SNOOZED


def test_dismiss_vereist_fysieke_bevestiging():
    _, _, core, speaker, lamp = _bouw(_ochtend())
    core.trigger()
    assert core.dismiss(physical=False) is False
    assert core.state is AlarmState.RINGING
    assert core.dismiss(physical=True) is True
    assert core.state is AlarmState.DISMISSED
    assert not speaker.is_playing and not lamp.is_on


def test_next_alarm_berekening():
    s, klok, core, _, _ = _bouw(_ochtend())
    assert core.next_alarm() == datetime(2026, 9, 17, 7, 30, tzinfo=timezone.utc)
    klok.set(datetime(2026, 9, 17, 8, 0, tzinfo=timezone.utc))
    assert core.next_alarm() == datetime(2026, 9, 18, 7, 30, tzinfo=timezone.utc)
    s.alarm.enabled = False
    assert core.next_alarm() is None


def test_next_alarm_tijdens_snooze():
    _, klok, core, _, _ = _bouw(_ochtend())
    klok.set(datetime(2026, 9, 17, 7, 30, tzinfo=timezone.utc))
    core.tick()
    assert core.snooze() is True
    assert core.next_alarm() == datetime(2026, 9, 17, 7, 39, tzinfo=timezone.utc)


def test_illegale_trigger_geeft_false():
    _, _, core, _, _ = _bouw(_ochtend())
    assert core.trigger() is True
    assert core.trigger() is False  # al RINGING


class KapotteSpeaker(MockSpeaker):
    def play(self, sound: str, volume: int) -> None:
        raise RuntimeError("GPIO weg")


def test_hardwarefout_laat_consistente_toestand_achter():
    s = default_settings()
    s.alarm.time = "07:30"
    klok = FakeClock(_ochtend())
    lamp = MockLamp()
    core = AlarmClock(s, klok, KapotteSpeaker(), lamp)
    klok.set(datetime(2026, 9, 17, 7, 30, tzinfo=timezone.utc))
    with pytest.raises(RuntimeError):
        core.tick()
    assert core.state is AlarmState.SLEEPING
    assert not lamp.is_on
    core._speaker = MockSpeaker()  # driver "vervangen"
    assert core.tick() is AlarmState.RINGING


def test_hardwarefout_tijdens_snooze_einde_niet_vast():
    s = default_settings()
    s.alarm.time = "07:30"
    klok = FakeClock(_ochtend())
    core = AlarmClock(s, klok, MockSpeaker(), MockLamp())
    klok.set(datetime(2026, 9, 17, 7, 30, tzinfo=timezone.utc))
    core.tick()
    assert core.snooze() is True
    core._speaker = KapotteSpeaker()
    klok.advance(timedelta(minutes=9))
    with pytest.raises(RuntimeError):
        core.tick()
    assert core.state is AlarmState.SNOOZED
    assert core.snooze_until is not None  # behouden voor herkansing
    core._speaker = MockSpeaker()
    assert core.tick() is AlarmState.RINGING


def test_gelijktijdige_aanroepen_blijven_consistent():
    import threading

    _, klok, core, _, _ = _bouw(_ochtend())
    klok.set(datetime(2026, 9, 17, 7, 30, tzinfo=timezone.utc))
    fouten: list[BaseException] = []

    def hameren():
        try:
            for _ in range(200):
                core.tick()
                core.snooze()
                core.dismiss(physical=True)
                core.status()
        except BaseException as exc:  # pragma: no cover
            fouten.append(exc)

    draden = [threading.Thread(target=hameren) for _ in range(4)]
    for draad in draden:
        draad.start()
    for draad in draden:
        draad.join()
    assert not fouten
    assert core.state in set(AlarmState)


def test_testgeluid_helpers():
    _, _, core, speaker, _ = _bouw(_ochtend())
    core.sound_start()
    assert speaker.is_playing
    assert core.speaker_playing is True
    core.sound_stop()
    assert not speaker.is_playing
