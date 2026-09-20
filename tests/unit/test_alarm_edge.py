"""Tests: alarm edge cases (middernacht, DST, runtime-wijzigingen).

Allemaal met FakeClock: nooit afhankelijk van echte systeemtijd.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from wekker.alarm.core import AlarmClock
from wekker.alarm.state import AlarmState
from wekker.clock import FakeClock
from wekker.hardware.mock import MockLamp, MockSpeaker
from wekker.settings import default_settings

AMS = ZoneInfo("Europe/Amsterdam")


def _bouw(start, wektijd="07:30"):
    s = default_settings()
    s.alarm.time = wektijd
    klok = FakeClock(start)
    core = AlarmClock(s, klok, MockSpeaker(), MockLamp())
    return s, klok, core


def test_uitgeschakeld_alarm_gaat_nooit_af():
    s, klok, core = _bouw(datetime(2026, 9, 17, 6, 0, tzinfo=timezone.utc))
    s.alarm.enabled = False
    for minuut in range(0, 24 * 60, 7):
        klok.set(datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=minuut))
        assert core.tick() is AlarmState.SLEEPING


def test_wektijd_wijzigen_tijdens_runtime():
    s, klok, core = _bouw(datetime(2026, 9, 17, 6, 0, tzinfo=timezone.utc))
    s.alarm.time = "09:00"
    core.update_settings(s)
    klok.set(datetime(2026, 9, 17, 7, 30, tzinfo=timezone.utc))
    assert core.tick() is AlarmState.SLEEPING  # oude tijd telt niet meer
    klok.set(datetime(2026, 9, 17, 9, 0, tzinfo=timezone.utc))
    assert core.tick() is AlarmState.RINGING


def test_uitschakelen_tijdens_runtime():
    s, klok, core = _bouw(datetime(2026, 9, 17, 6, 0, tzinfo=timezone.utc))
    s.alarm.enabled = False
    core.update_settings(s)
    assert core.next_alarm() is None
    klok.set(datetime(2026, 9, 17, 7, 30, tzinfo=timezone.utc))
    assert core.tick() is AlarmState.SLEEPING


def test_alarm_over_middernacht():
    _, klok, core = _bouw(datetime(2026, 9, 17, 23, 50, tzinfo=timezone.utc),
                           wektijd="00:05")
    klok.set(datetime(2026, 9, 18, 0, 5, tzinfo=timezone.utc))
    assert core.tick() is AlarmState.RINGING
    assert core.dismiss(physical=True) is True
    # Volgende dag weer scherp, zonder dubbele trigger vandaag.
    klok.set(datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc))
    assert core.tick() is AlarmState.DISMISSED
    klok.set(datetime(2026, 9, 19, 0, 5, tzinfo=timezone.utc))
    assert core.tick() is AlarmState.SLEEPING
    assert core.tick() is AlarmState.RINGING


def test_snooze_over_middernacht():
    s, klok, core = _bouw(datetime(2026, 9, 17, 23, 50, tzinfo=timezone.utc),
                           wektijd="23:58")
    s.alarm.snooze_minutes = 5
    klok.set(datetime(2026, 9, 17, 23, 58, tzinfo=timezone.utc))
    assert core.tick() is AlarmState.RINGING
    assert core.snooze() is True
    assert core.next_alarm() == datetime(2026, 9, 18, 0, 3, tzinfo=timezone.utc)
    klok.set(datetime(2026, 9, 18, 0, 3, tzinfo=timezone.utc))
    assert core.tick() is AlarmState.RINGING


def test_voorjaar_dst_sprong_zonder_crash():
    # 2026-03-29: 02:00 -> 03:00. Alarm om 03:05 moet die dag gewoon afgaan.
    _, klok, core = _bouw(datetime(2026, 3, 29, 0, 0, tzinfo=AMS), wektijd="03:05")
    toestanden = set()
    moment = datetime(2026, 3, 29, 0, 0, tzinfo=AMS)
    for _ in range(5 * 60):
        klok.set(moment)
        toestanden.add(core.tick())
        moment += timedelta(minutes=1)
    assert AlarmState.RINGING in toestanden


def test_najaar_dst_geen_dubbele_trigger():
    # 2026-10-25: 03:00 -> 02:00; 02:30 komt twee keer voor (fold 0 en 1).
    # Per datum mag het alarm maar één keer afgaan.
    _, klok, core = _bouw(datetime(2026, 10, 25, 0, 0, tzinfo=AMS), wektijd="02:30")
    telling = 0
    moment = datetime(2026, 10, 25, 0, 0, tzinfo=AMS)
    for _ in range(6 * 60):
        klok.set(moment)
        if core.tick() is AlarmState.RINGING:
            telling += 1
            assert core.dismiss(physical=True) is True
        moment += timedelta(minutes=1)
    assert telling == 1
