from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import threading
import time

import pytest

from wekker.agenda.cache import AgendaCache
from wekker.agenda.models import DaySchedule, Lesson
from wekker.alarm.core import AlarmClock, RECOVERY_WINDOW
from wekker.alarm.persistence import AlarmRuntimeStore
from wekker.alarm.state import AlarmState
from wekker.clock import FakeClock
from wekker.diagnostics import export_diagnostics
from wekker.gui.screens import AGENDA_PAGE_SIZE, build_agenda_data, build_main_data
from wekker.hardware.mock import MockLamp, MockSpeaker
from wekker.main import apply_runtime_settings, build_default, run_once, shutdown
from wekker.settings import default_settings
from wekker.storage import StorageError
from wekker.touch_setup import (
    BOOT_BEGIN,
    PROFILE_ID,
    TOUCH_NAME,
    TouchConfigurator,
    TouchSetupError,
)


TZ = timezone.utc


def lesson(
    day: date,
    hour: int,
    minute: int,
    duration: int = 50,
    *,
    subject: str = "Les",
    room: str = "LVM-E2.12",
    teacher: str = "DOC",
    source: str = "myx",
) -> Lesson:
    start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)
    return Lesson(
        subject=subject,
        start=start,
        end=start + timedelta(minutes=duration),
        room=room,
        teacher=teacher,
        source=source,
    )


def make_alarm(tmp_path: Path, now: datetime, *, alarm_time: str = "07:30"):
    settings = default_settings().update_from_dict(
        {"alarm": {"time": alarm_time, "snooze_minutes": 5}}
    )
    clock = FakeClock(now)
    speaker = MockSpeaker()
    lamp = MockLamp()
    store = AlarmRuntimeStore(tmp_path / "alarm.json")
    core = AlarmClock(settings, clock, speaker, lamp, runtime_store=store)
    return settings, clock, speaker, lamp, store, core


def test_agenda_cache_overleeft_offline_restart_en_houdt_laatste_success(tmp_path: Path):
    path = tmp_path / "agenda.json"
    day = date(2026, 9, 17)
    cache = AgendaCache(path=path)
    cache.put_day(day, [lesson(day, 8, 30, subject="Netwerkbeheer")])
    success = datetime(2026, 9, 17, 6, 0, tzinfo=TZ)
    cache.mark_ok(success)

    restarted = AgendaCache(path=path)
    assert restarted.is_day_loaded(day)
    assert restarted.get_day(day)[0].room == "LVM-E2.12"
    assert restarted.last_success == success

    failed = success + timedelta(hours=2)
    restarted.mark_attempt(failed)
    restarted.mark_error(failed, "internet weg")
    assert restarted.last_success == success
    assert restarted.last_attempt == failed
    assert restarted.get_day(day)[0].subject == "Netwerkbeheer"
    assert restarted.display_status(failed) == "Eerder rooster getoond · bijgewerkt om 06:00"


def test_corrupt_agendacache_wordt_apart_gezet(tmp_path: Path):
    path = tmp_path / "agenda.json"
    path.write_text("{dit is geen json", encoding="utf-8")
    cache = AgendaCache(path=path)
    assert cache.status == "never"
    assert cache.days == {}
    assert not path.exists()
    assert list(tmp_path.glob("agenda.json.corrupt-*"))


def test_dayschedule_roundtrip():
    day = date(2026, 9, 17)
    original = DaySchedule(day, [lesson(day, 8, 30), lesson(day, 10, 0)])
    restored = DaySchedule.from_dict(original.to_dict())
    assert restored.day == day
    assert [item.start for item in restored.lessons] == [item.start for item in original.lessons]


def test_alarm_snooze_en_dismiss_overleven_herstart(tmp_path: Path):
    settings, clock, _speaker, _lamp, store, core = make_alarm(
        tmp_path, datetime(2026, 9, 17, 7, 30, tzinfo=TZ)
    )
    assert core.tick() is AlarmState.RINGING
    assert core.snooze()
    expected = datetime(2026, 9, 17, 7, 35, tzinfo=TZ)
    assert core.snooze_until == expected

    clock.set(datetime(2026, 9, 17, 7, 32, tzinfo=TZ))
    restarted = AlarmClock(settings, clock, MockSpeaker(), MockLamp(), runtime_store=store)
    assert restarted.state is AlarmState.SNOOZED
    assert restarted.snooze_until == expected

    clock.set(expected)
    assert restarted.tick() is AlarmState.RINGING
    assert restarted.dismiss(physical=True)
    assert restarted.state is AlarmState.DISMISSED

    clock.set(datetime(2026, 9, 17, 7, 45, tzinfo=TZ))
    again = AlarmClock(settings, clock, MockSpeaker(), MockLamp(), runtime_store=store)
    assert again.state is AlarmState.DISMISSED
    assert again.tick() is AlarmState.DISMISSED


def test_alarm_buiten_herstelvenster_rinkelt_niet_laat(tmp_path: Path):
    settings, clock, _speaker, _lamp, store, core = make_alarm(
        tmp_path, datetime(2026, 9, 17, 7, 30, tzinfo=TZ)
    )
    assert core.tick() is AlarmState.RINGING

    clock.set(datetime(2026, 9, 17, 7, 30, tzinfo=TZ) + RECOVERY_WINDOW + timedelta(seconds=1))
    restarted = AlarmClock(settings, clock, MockSpeaker(), MockLamp(), runtime_store=store)
    assert restarted.state is AlarmState.DISMISSED
    assert "gemist" in restarted.missed_notice.lower()


class FailStopOnceSpeaker(MockSpeaker):
    def __init__(self):
        super().__init__()
        self.fail_stop_once = False

    def stop(self) -> None:
        if self.fail_stop_once:
            self.fail_stop_once = False
            raise RuntimeError("eenmalige speakerfout")
        super().stop()


class FailPlayOnceSpeaker(MockSpeaker):
    def __init__(self):
        super().__init__()
        self.fail_play_once = True

    def play(self, sound: str, volume: int) -> None:
        if self.fail_play_once:
            self.fail_play_once = False
            raise RuntimeError("eenmalige speakerfout")
        super().play(sound, volume)


def test_driverfout_commit_geen_half_snooze(tmp_path: Path):
    settings = default_settings().update_from_dict(
        {"alarm": {"time": "07:30", "snooze_minutes": 5}}
    )
    clock = FakeClock(datetime(2026, 9, 17, 7, 30, tzinfo=TZ))
    speaker = FailStopOnceSpeaker()
    core = AlarmClock(settings, clock, speaker, MockLamp())
    assert core.tick() is AlarmState.RINGING
    speaker.fail_stop_once = True

    with pytest.raises(RuntimeError):
        core.snooze()
    assert core.state is AlarmState.RINGING
    assert core.snooze_until is None
    assert speaker.is_playing  # rollback herstelt de oude hardwaretoestand

    assert core.snooze()
    assert core.state is AlarmState.SNOOZED
    assert core.snooze_until == datetime(2026, 9, 17, 7, 35, tzinfo=TZ)


def test_driverfout_bij_start_is_retrybaar():
    settings = default_settings().update_from_dict({"alarm": {"time": "07:30"}})
    clock = FakeClock(datetime(2026, 9, 17, 7, 30, tzinfo=TZ))
    speaker = FailPlayOnceSpeaker()
    core = AlarmClock(settings, clock, speaker, MockLamp())

    with pytest.raises(RuntimeError):
        core.tick()
    assert core.state is AlarmState.SLEEPING
    assert core.ringing_since is None

    assert core.tick() is AlarmState.RINGING
    assert speaker.is_playing


def test_30_seconden_netwerkblokkade_blokkeert_alarmloop_niet(tmp_path: Path):
    rt = build_default(tmp_path / "settings.json")
    release = threading.Event()
    started = threading.Event()

    def very_slow_request():
        started.set()
        # Dit modelleert een request die 30 s zou blokkeren. De test laat hem
        # direct na de timingassertie los om de suite niet echt 30 s te vertragen.
        release.wait(30)
        return True

    assert rt.background is not None
    assert rt.background.submit("agenda-sync", very_slow_request)
    assert started.wait(1)

    fake = FakeClock(datetime(2026, 9, 17, 7, 30, tzinfo=TZ))
    rt.ctx.clock = fake
    rt.ctx.core._clock = fake
    rt.ctx.core.update_settings(
        rt.ctx.settings.update_from_dict({"alarm": {"time": "07:30"}})
    )

    begin = time.monotonic()
    run_once(rt)
    elapsed = time.monotonic() - begin
    assert elapsed < 0.25
    assert rt.ctx.core.state is AlarmState.RINGING

    release.set()
    shutdown(rt)


def _runner_for(output: str = "HDMI-A-1", resolution: str = "800x480"):
    calls: list[list[str]] = []

    def run(args, **_kwargs):
        calls.append(list(args))
        if args and args[0] == "wlr-randr":
            return SimpleNamespace(
                stdout=(
                    f"{output} \"Waveshare\"\n"
                    "  Enabled: yes\n"
                    f"  {resolution} px, 60.000000 Hz (current)\n"
                ),
                returncode=0,
            )
        return SimpleNamespace(stdout="", returncode=0)

    return run, calls


def test_touchhelper_repareert_verkeerde_mapping_idempotent(tmp_path: Path):
    home = tmp_path / "home"
    labwc = home / ".config/labwc/rc.xml"
    labwc.parent.mkdir(parents=True)
    labwc.write_text(
        '<openbox_config><touch deviceName="ADS7846 Touchscreen" '
        'mapToOutput="HDMI-A-2" mouseEmulation="yes" /></openbox_config>',
        encoding="utf-8",
    )
    inputs = tmp_path / "devices"
    inputs.write_text(f"N: Name=\"{TOUCH_NAME}\"\n", encoding="utf-8")
    boot = tmp_path / "config.txt"
    boot.write_text("# bestaand\n", encoding="utf-8")
    runner, calls = _runner_for()

    manager = TouchConfigurator(
        home=home,
        boot_config=boot,
        input_devices=inputs,
        command_runner=runner,
    )
    before = manager.detect()
    assert before.detected_touch and not before.mapping_ok

    after = manager.apply()
    assert after.mapping_ok
    assert 'mapToOutput="HDMI-A-1"' in labwc.read_text(encoding="utf-8")
    assert boot.read_text(encoding="utf-8") == "# bestaand\n"
    backups_before = sorted(labwc.parent.glob("rc.xml.wakesync-backup-*"))

    again = manager.apply()
    assert again.mapping_ok
    assert sorted(labwc.parent.glob("rc.xml.wakesync-backup-*")) == backups_before
    assert any(call and call[0] == "labwc" for call in calls)


def test_touchhelper_onbekende_driver_vraagt_eerst_bevestiging(tmp_path: Path):
    home = tmp_path / "home"
    inputs = tmp_path / "devices"
    inputs.write_text("", encoding="utf-8")
    boot = tmp_path / "config.txt"
    boot.write_text("# boot\n", encoding="utf-8")
    runner, _ = _runner_for()
    manager = TouchConfigurator(
        home=home,
        boot_config=boot,
        input_devices=inputs,
        command_runner=runner,
    )
    with pytest.raises(TouchSetupError, match="expliciet"):
        manager.apply(profile=PROFILE_ID, confirmed=False)
    assert BOOT_BEGIN not in boot.read_text(encoding="utf-8")

    status = manager.apply(profile=PROFILE_ID, confirmed=True)
    assert status.restart_required
    assert BOOT_BEGIN in boot.read_text(encoding="utf-8")
    assert list(tmp_path.glob("config.txt.wakesync-backup-*"))


def test_main_toont_huidige_les_en_groot_lokaal():
    day = date(2026, 9, 17)
    now = datetime(2026, 9, 17, 9, 0, tzinfo=TZ)
    items = [
        lesson(day, 8, 30, duration=90, subject="Een erg lange vaknaam die mag inkorten", room="LVM-E2.12"),
        lesson(day, 10, 30, subject="Volgende", room="LVM-E3.04"),
    ]
    data = build_main_data(
        now,
        datetime(2026, 9, 18, 7, 30, tzinfo=TZ),
        lessons=items,
        agenda_loaded=True,
        agenda_status="Bijgewerkt om 08:55",
    )
    assert data.lesson_label == "HUIDIGE LES"
    assert data.lesson_room == "LVM-E2.12"
    assert data.lesson_time == "08:30 – 10:00"
    assert data.alarm_day == "Morgen"


def test_volledige_dagagenda_pagineert_12_lessen_zonder_verlies():
    day = date(2026, 9, 17)
    items = []
    start = datetime(2026, 9, 17, 8, 0, tzinfo=TZ)
    for index in range(12):
        s = start + timedelta(minutes=55 * index)
        items.append(
            Lesson(
                subject=f"Vak {index + 1}",
                start=s,
                end=s + timedelta(minutes=45),
                room=f"L{index + 1}",
                source="myx",
            )
        )

    pages = [
        build_agenda_data(items, "MyX", page=page, now=start + timedelta(minutes=60))
        for page in range(3)
    ]
    assert all(len(page.rows) <= AGENDA_PAGE_SIZE for page in pages)
    assert all(page.page_count == 3 for page in pages)
    assert [row.subject for page in pages for row in page.rows] == [
        f"Vak {i}" for i in range(1, 13)
    ]


def test_agenda_markeert_overlap_pauze_actuele_les_en_eerlijke_leegstatus():
    day = date(2026, 9, 17)
    first = lesson(day, 8, 30, duration=60, subject="A")
    overlap = lesson(day, 9, 15, duration=45, subject="B")
    pause = lesson(day, 10, 30, duration=45, subject="C")
    data = build_agenda_data(
        [first, overlap, pause],
        "MyX",
        now=datetime(2026, 9, 17, 9, 20, tzinfo=TZ),
        loaded=True,
    )
    assert data.rows[1].relation_before == "OVERLAP"
    assert data.rows[1].current
    assert data.rows[2].relation_before == "PAUZE 30 MIN"

    unknown = build_agenda_data([], "MyX", loaded=False)
    assert unknown.empty_text == "Nog niet geladen"
    confirmed_empty = build_agenda_data([], "MyX", loaded=True)
    assert confirmed_empty.empty_text == "Geen lessen op deze dag"


def test_instellingenopslagfout_verandert_runtime_niet(tmp_path: Path):
    rt = build_default(tmp_path / "settings.json")
    old = rt.ctx.settings
    old_tz = rt.ctx.clock.timezone_name

    class BrokenStore:
        def save(self, _data):
            raise StorageError("sd-kaart niet schrijfbaar")

    rt.ctx.store = BrokenStore()
    new = old.update_from_dict({"locale": {"timezone": "UTC"}})
    with pytest.raises(StorageError):
        apply_runtime_settings(rt, new)
    assert rt.ctx.settings is old
    assert rt.ctx.clock.timezone_name == old_tz
    shutdown(rt)

def test_alarmruntime_schema1_migreert_veilig_naar_schema2(tmp_path: Path):
    path = tmp_path / "alarm-v1.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "state": "dismissed",
                "ringing_since": None,
                "snooze_until": None,
                "last_trigger_date": "2026-09-17",
                "dismissed_date": "2026-09-17",
                "missed_notice": "",
            }
        ),
        encoding="utf-8",
    )

    snapshot = AlarmRuntimeStore(path).load()

    assert snapshot is not None
    assert snapshot.state == "dismissed"
    assert snapshot.dismissed_date == "2026-09-17"
    assert snapshot.missed_date is None


def test_synthetisch_gemist_alarm_wordt_na_achterwaartse_klokcorrectie_hersteld(
    tmp_path: Path,
):
    _settings, clock, _speaker, _lamp, _store, core = make_alarm(
        tmp_path, datetime(2026, 9, 17, 12, 0, tzinfo=TZ)
    )

    # De systeemklok stond ten onrechte al ruim na het alarm.
    assert core.tick() is AlarmState.DISMISSED
    assert "gemist" in core.missed_notice.lower()

    # NTP corrigeert daarna terug naar vóór de echte alarmtijd.
    clock.set(datetime(2026, 9, 17, 7, 0, tzinfo=TZ))
    assert core.tick() is AlarmState.SLEEPING
    assert core.missed_notice == ""

    # Op de werkelijke alarmtijd moet het alarm alsnog normaal afgaan.
    clock.set(datetime(2026, 9, 17, 7, 30, tzinfo=TZ))
    assert core.tick() is AlarmState.RINGING


def test_echte_fysieke_dismiss_wordt_niet_door_klokcorrectie_ongedaan_gemaakt(
    tmp_path: Path,
):
    _settings, clock, _speaker, _lamp, _store, core = make_alarm(
        tmp_path, datetime(2026, 9, 17, 7, 30, tzinfo=TZ)
    )
    assert core.tick() is AlarmState.RINGING
    assert core.dismiss(physical=True)
    assert core.state is AlarmState.DISMISSED

    # Zelfs als de systeemklok teruggaat, blijft een echte gebruikersactie gelden.
    clock.set(datetime(2026, 9, 17, 7, 0, tzinfo=TZ))
    assert core.tick() is AlarmState.DISMISSED

    clock.set(datetime(2026, 9, 17, 7, 30, tzinfo=TZ))
    assert core.tick() is AlarmState.DISMISSED

def test_diagnose_export_bevat_geen_geheime_velden(tmp_path: Path, monkeypatch):
    # Maak de test onafhankelijk van de echte hostcommands/hardware.
    monkeypatch.setattr("wekker.diagnostics._command", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        "wekker.diagnostics.TouchConfigurator.detect",
        lambda self: SimpleNamespace(to_dict=lambda: {"configured": True}),
    )

    target = export_diagnostics(tmp_path / "diagnose.json")
    raw = target.read_text(encoding="utf-8").lower()

    for secret_key in (
        "device_key",
        "initial_password",
        "management_password",
        "feed_url",
        "bearer_token",
        "myx_feed",
    ):
        assert secret_key not in raw

