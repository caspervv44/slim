"""Tests: mocks, agenda, display (eerste prototype, zonder motor)."""

from datetime import date, datetime, timedelta, timezone

import pytest

from wekker.agenda.cache import AgendaCache
from wekker.agenda.models import DaySchedule, Lesson
from wekker.agenda.providers import MockAgendaProvider, ProviderError, create_provider
from wekker.agenda.sync import AgendaSyncService
from wekker.clock import FakeClock
from wekker.display.manager import DisplayManager
from wekker.hardware.mock import (
    MockButton,
    MockDisplay,
    MockLamp,
    MockSpeaker,
)
from wekker.settings import default_settings


def _les(start_uur=8, dag=17):
    tz = timezone.utc
    s = datetime(2026, 9, dag, start_uur, 30, tzinfo=tz)
    return Lesson(subject="Wiskunde", start=s, end=s + timedelta(minutes=50),
                  teacher="J. Jansen", room="A101")


def test_lesson_validatie():
    tz = timezone.utc
    with pytest.raises(ValueError):
        Lesson(subject="", start=datetime(2026, 9, 17, 8, 30, tzinfo=tz),
               end=datetime(2026, 9, 17, 9, 20, tzinfo=tz))
    with pytest.raises(ValueError):  # end voor start
        Lesson(subject="X", start=datetime(2026, 9, 17, 9, 30, tzinfo=tz),
               end=datetime(2026, 9, 17, 8, 30, tzinfo=tz))
    with pytest.raises(ValueError):  # naive datetimes
        Lesson(subject="X", start=datetime(2026, 9, 17, 8, 30),
               end=datetime(2026, 9, 17, 9, 20))


def test_lesson_serialisatie_voor_api():
    data = _les().to_dict()
    assert data["title"] == "Wiskunde"
    assert data["location"] == "A101"
    assert data["teacher"] == "J. Jansen"
    assert data["source"] == "mock"
    assert data["simulated"] is True
    assert "start_time" in data and "end_time" in data


def test_dayschedule_sorteert_en_first_last():
    l1, l2 = _les(10), _les(8)
    schema = DaySchedule(day=date(2026, 9, 17), lessons=[l1, l2])
    assert schema.first == l2
    assert schema.last == l1
    assert DaySchedule(day=date(2026, 9, 17), lessons=[]).first is None


def test_mock_provider_weekdag_en_weekend():
    p = MockAgendaProvider()
    maandag = p.fetch_day(date(2026, 9, 14))  # maandag
    assert len(maandag) == 4
    assert maandag[0].subject == "Wiskunde"
    assert all(les.source == "mock" for les in maandag)
    assert p.fetch_day(date(2026, 9, 19)) == []  # zaterdag
    p.fail = True
    with pytest.raises(ProviderError):
        p.fetch_day(date(2026, 9, 14))


def test_providerregister_eerlijk_over_ontbrekende_adapters():
    assert create_provider("mock").name == "mock"
    with pytest.raises(ProviderError) as exc:
        create_provider("magister")
    assert "nog niet beschikbaar" in str(exc.value)


def test_cache_en_sync_ok_en_error():
    klok = FakeClock(datetime(2026, 9, 14, 7, 0, tzinfo=timezone.utc))
    cache = AgendaCache()
    sync = AgendaSyncService(MockAgendaProvider(), cache, klok)
    assert sync.sync_day(date(2026, 9, 14)) is True
    assert cache.status == "ok"
    assert len(cache.get_day(date(2026, 9, 14))) == 4
    assert cache.get_day(date(2026, 9, 15)) == []

    sync_fout = AgendaSyncService(MockAgendaProvider(fail=True), cache, klok)
    assert sync_fout.sync_day(date(2026, 9, 15)) is False
    assert cache.status == "error"
    assert cache.error
    # eerdere cache blijft behouden bij fout
    assert len(cache.get_day(date(2026, 9, 14))) == 4


def test_cache_stale_onderscheidt_vers_van_verouderd():
    klok = FakeClock(datetime(2026, 9, 14, 7, 0, tzinfo=timezone.utc))
    cache = AgendaCache()
    assert cache.is_stale(klok.now()) is True  # nooit gesynchroniseerd
    sync = AgendaSyncService(MockAgendaProvider(), cache, klok)
    assert sync.sync_today() is True
    assert cache.is_stale(klok.now()) is False  # vers
    klok.advance(timedelta(hours=25))
    assert cache.is_stale(klok.now()) is True  # verouderd


def test_display_render_bevat_velden():
    klok = FakeClock(datetime(2026, 9, 14, 7, 0, tzinfo=timezone.utc))
    cache = AgendaCache()
    cache.put_day(date(2026, 9, 14), [_les(8, dag=14), _les(10, dag=14)])
    s = default_settings()
    mgr = DisplayManager(MockDisplay(), s, klok, cache)
    mgr.set_alarm_context("sleeping", "07:30")
    model = mgr.render()
    tekst = "\n".join(model.lines)
    assert "07:00" in tekst
    assert "Alarm: 07:30" in tekst
    assert "Wiskunde" in tekst
    assert "J. Jansen" in tekst
    assert "A101" in tekst


def test_display_toont_alarmstatus_en_melding():
    klok = FakeClock(datetime(2026, 9, 14, 7, 0, tzinfo=timezone.utc))
    mgr = DisplayManager(MockDisplay(), default_settings(), klok, AgendaCache())
    mgr.set_alarm_context("ringing", "07:30")
    assert "ALARM!" in "\n".join(mgr.render().lines)
    mgr.set_alarm_context("snoozed", None)
    assert "Snooze..." in "\n".join(mgr.render().lines)
    mgr.set_notice("Lamp aan (button)")
    assert "Lamp aan (button)" in "\n".join(mgr.render().lines)
    mgr.clear_notice()
    assert "Lamp aan (button)" not in "\n".join(mgr.render().lines)


def test_display_zonder_lessen():
    klok = FakeClock(datetime(2026, 9, 19, 9, 0, tzinfo=timezone.utc))  # zaterdag
    mgr = DisplayManager(MockDisplay(), default_settings(), klok, AgendaCache())
    assert "Geen lessen" in "\n".join(mgr.render().lines)


def test_display_auto_uit_en_nachtmodus():
    klok = FakeClock(datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc))
    driver = MockDisplay()
    s = default_settings()
    s.display.on_duration_seconds = 30
    mgr = DisplayManager(driver, s, klok, AgendaCache())
    mgr.button_pressed()
    assert mgr.visible and not driver.cleared
    klok.advance(timedelta(seconds=31))
    mgr.tick()
    assert not mgr.visible and driver.cleared

    # nachtmodus 'off': refresh toont niets 's nachts
    klok.set(datetime(2026, 9, 14, 23, 30, tzinfo=timezone.utc))
    s.display.night_mode = "off"
    mgr.button_pressed()
    assert not mgr.visible


def test_mocks_houden_toestand_bij():
    lamp, speaker = MockLamp(), MockSpeaker()
    lamp.on(80, blink=True, pattern="blink")
    assert lamp.is_on and lamp.blink
    lamp.off()
    assert not lamp.is_on
    speaker.play("beep", 70)
    assert speaker.is_playing
    speaker.stop()
    assert not speaker.is_playing
    with pytest.raises(ValueError):
        speaker.play("beep", 101)

    knop = MockButton()
    gezien = []
    knop.on_press(lambda: gezien.append("knop"))
    knop.press()
    assert gezien == ["knop"]
    assert knop.press_count == 1
