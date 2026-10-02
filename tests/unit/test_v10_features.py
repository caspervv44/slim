from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from PIL import Image

from wekker.agenda.myx import inspect_ics_room_hints, parse_ics
from wekker.alarm.core import AlarmClock
from wekker.alarm.state import AlarmState
from wekker.clock import FakeClock
from wekker.gui.app import SLEEP_EFFECT_CHOICES
from wekker.gui.screens import AGENDA_PAGE_SIZE, build_agenda_data, build_main_data
from wekker.hardware.mock import MockLamp, MockSpeaker
from wekker.settings import AlarmSettings, Settings


def _ics(extra: str, *, location: str = "-") -> str:
    return f"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:v10-room
DTSTART;TZID=W. Europe Standard Time:20261001T153000
DTEND;TZID=W. Europe Standard Time:20261001T170000
SUMMARY:Project
LOCATION:{location}
{extra}
END:VEVENT
END:VCALENDAR
"""


def test_c9_logo_is_hoogresolutie_transparant_en_niet_afgesneden():
    assets = Path(__file__).parents[2] / "src" / "wekker" / "assets"
    for name in ("wakesync-logo.png", "wakesync-logo-dark.png"):
        image = Image.open(assets / name).convert("RGBA")
        assert image.width >= 1000
        assert image.height >= 400
        alpha = image.getchannel("A")
        bbox = alpha.getbbox()
        assert bbox is not None
        # Rondom het volledige merk staat echte transparante marge:
        # geen afgesneden W/S of losse randpixels.
        left, top, right, bottom = bbox
        assert left >= 20 and top >= 20
        assert image.width - right >= 20
        assert image.height - bottom >= 20
        assert alpha.getextrema()[0] == 0
        assert alpha.getextrema()[1] == 255


def test_liquid_motion_blijft_naast_bestaande_slaapeffecten_beschikbaar():
    values = {value for value, _ in SLEEP_EFFECT_CHOICES}
    assert {
        "off", "soft_glow", "pulse_glow", "aurora", "liquid_motion"
    }.issubset(values)

    settings = Settings().update_from_dict(
        {"display": {"sleep_effect": "liquid_motion", "sleep_glow_intensity": 88}}
    )
    assert settings.display.sleep_effect == "liquid_motion"
    assert settings.display.sleep_glow_intensity == 88
    restored = Settings.from_dict(settings.to_dict())
    assert restored.display.sleep_effect == "liquid_motion"


def test_legacy_enkel_alarm_wordt_automatisch_v10_profiel():
    alarm = AlarmSettings(time="06:45", enabled=False, snooze_minutes=10)
    assert len(alarm.alarms) == 1
    profile = alarm.alarms[0]
    assert profile.id == "alarm-1"
    assert profile.time == "06:45"
    assert profile.enabled is False
    assert profile.snooze_minutes == 10


def test_meerdere_alarmprofielen_roundtrip_en_tijdvolgorde():
    settings = Settings.from_dict(
        {
            "alarm": {
                "alarms": [
                    {"id": "late", "time": "08:10", "enabled": True},
                    {"id": "early", "time": "06:55", "enabled": False},
                ]
            }
        }
    )
    assert [a.id for a in settings.alarm.alarms] == ["early", "late"]
    restored = Settings.from_dict(settings.to_dict())
    assert [(a.id, a.time, a.enabled) for a in restored.alarm.alarms] == [
        ("early", "06:55", False),
        ("late", "08:10", True),
    ]


def test_legacy_alarm_patch_wordt_op_eerste_profiel_toegepast():
    settings = Settings.from_dict(
        {
            "alarm": {
                "alarms": [
                    {"id": "a", "time": "06:30", "enabled": True, "volume": 50},
                    {"id": "b", "time": "08:00", "enabled": True, "volume": 60},
                ]
            }
        }
    )
    changed = settings.update_from_dict({"alarm": {"volume": 80}})
    assert changed.alarm.alarms[0].volume == 80
    assert changed.alarm.alarms[1].volume == 60


def _multi_alarm_core(start: datetime):
    settings = Settings.from_dict(
        {
            "alarm": {
                "alarms": [
                    {"id": "vroeg", "time": "07:00", "enabled": True},
                    {"id": "laat", "time": "08:00", "enabled": True},
                ]
            }
        }
    )
    clock = FakeClock(start)
    core = AlarmClock(settings, clock, MockSpeaker(), MockLamp())
    return settings, clock, core


def test_alarm_core_kiest_eerstvolgende_ingeschakelde_alarm():
    _, clock, core = _multi_alarm_core(
        datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)
    )
    assert core.next_alarm() == datetime(2026, 10, 1, 7, 0, tzinfo=timezone.utc)
    clock.set(datetime(2026, 10, 1, 7, 20, tzinfo=timezone.utc))
    # Het gemiste vroege alarm ligt buiten herstelvenster, het late alarm blijft gepland.
    core.tick()
    assert core.next_alarm() == datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)


def test_stoppen_vroeg_alarm_blokkeert_later_alarm_niet():
    _, clock, core = _multi_alarm_core(
        datetime(2026, 10, 1, 6, 55, tzinfo=timezone.utc)
    )
    clock.set(datetime(2026, 10, 1, 7, 0, tzinfo=timezone.utc))
    assert core.tick() is AlarmState.RINGING
    assert core.active_alarm_id == "vroeg"
    assert core.dismiss(physical=True)
    clock.set(datetime(2026, 10, 1, 7, 1, tzinfo=timezone.utc))
    assert core.tick() is AlarmState.SLEEPING
    clock.set(datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc))
    assert core.tick() is AlarmState.RINGING
    assert core.active_alarm_id == "laat"


def test_myx_room_uit_attendee_cutype_room_cn():
    lesson = parse_ics(
        _ics("ATTENDEE;CUTYPE=ROOM;CN=LVM-E2.12:mailto:room@example.test")
    )[0]
    assert lesson.room == "LVM-E2.12"


def test_myx_room_uit_resources_en_vendor_location():
    lesson = parse_ics(_ics("RESOURCES:LVM-E3.07"))[0]
    assert lesson.room == "LVM-E3.07"

    vendor = parse_ics(
        _ics("X-MICROSOFT-CDO-LOCATION:LVM E4.11", location="—")
    )[0]
    assert vendor.room == "LVM-E4.11"


def test_myx_room_uit_gelabelde_numerieke_ruimte():
    lesson = parse_ics(_ics("DESCRIPTION:Docent: KAMJ\\nLokaal: 2.12"))[0]
    assert lesson.room == "2.12"


def test_myx_zonder_lokaal_blijft_echt_leeg_en_gui_toont_geen_streep():
    lesson = parse_ics(_ics("DESCRIPTION:Projectles zonder ruimte", location="-"))[0]
    assert lesson.room == ""

    now = datetime(2026, 10, 1, 16, 0, tzinfo=lesson.start.tzinfo)
    main = build_main_data(now, None, lessons=[lesson], agenda_loaded=True)
    agenda = build_agenda_data([lesson], "MyX / Xedule", now=now, loaded=True)
    assert main.lesson_room == ""
    assert agenda.rows[0].room == ""


def test_projectles_1530_1700_blijft_op_agenda_met_zes_lessen():
    tz = timezone.utc
    day = date(2026, 10, 1)
    times = [
        (8, 30, 9, 30),
        (9, 45, 10, 45),
        (11, 0, 12, 0),
        (12, 30, 13, 30),
        (13, 45, 15, 15),
        (15, 30, 17, 0),
    ]
    from wekker.agenda.models import Lesson

    lessons = [
        Lesson(
            subject="Project",
            start=datetime(day.year, day.month, day.day, sh, sm, tzinfo=tz),
            end=datetime(day.year, day.month, day.day, eh, em, tzinfo=tz),
            room=f"LVM-E{i+1}.01",
            source="myx",
        )
        for i, (sh, sm, eh, em) in enumerate(times)
    ]
    data = build_agenda_data(
        lessons,
        "MyX / Xedule",
        now=datetime(2026, 10, 1, 16, 0, tzinfo=tz),
        loaded=True,
    )
    assert AGENDA_PAGE_SIZE >= 6
    assert data.page_count == 1
    assert data.total_rows == 6
    assert data.rows[-1].start_str == "15:30"
    assert data.rows[-1].end_str == "17:00"
    assert data.rows[-1].room == "LVM-E6.01"


def test_product_cli_heeft_veilig_inspect_myx_en_geen_touch_setup():
    source = (
        Path(__file__).parents[2] / "src" / "wekker" / "main.py"
    ).read_text(encoding="utf-8")
    assert '"inspect-myx"' in source
    assert 'sub.add_parser("touch-setup"' not in source


def test_agenda_gui_herbouwt_als_lokaal_na_sync_verschijnt():
    source = (
        Path(__file__).parents[2] / "src" / "wekker" / "gui" / "app.py"
    ).read_text(encoding="utf-8")
    assert '"has_room": bool(room_value)' in source
    assert (
        'bool(w.get("has_room")) != bool(str(r.get("room") or "").strip())'
        in source
    )


def test_myx_room_met_gelijkteken_en_html_wordt_gevonden():
    lesson = parse_ics(
        _ics(
            "X-ALT-DESC;FMTTYPE=text/html:"
            "<div>Docent = KAMJ</div><div>Locatie = LVM-E5.09</div>",
            location="-",
        )
    )[0]
    assert lesson.room == "LVM-E5.09"


def test_myx_location_met_meerdere_lokalen_blijft_compact():
    lesson = parse_ics(
        _ics("", location="LVM-E2.12 / E2.14 - LVM +1")
    )[0]
    assert lesson.room == "LVM-E2.12 / E2.14"


def test_alarm_wizard_hoek_mapping_is_stabiel():
    # 12 uur / 00 minuten ligt bovenaan, rechts is een kwart van de cirkel.
    from wekker.gui.app import TouchApp

    assert TouchApp._angle_value(400, 100, 400, 264, 24) == 0
    assert TouchApp._angle_value(564, 264, 400, 264, 24) == 6
    assert TouchApp._angle_value(400, 100, 400, 264, 60) == 0
    assert TouchApp._angle_value(564, 264, 400, 264, 60) == 15


def test_myx_provider_gebruikt_v10_1_user_agent():
    source = (
        Path(__file__).parents[2] / "src" / "wekker" / "agenda" / "myx.py"
    ).read_text(encoding="utf-8")
    assert '"User-Agent": "WakeSync/10.1.0"' in source


def test_privacyvriendelijke_room_hints_zien_bronveld_zonder_feed_url():
    ics = _ics(
        "ATTENDEE;CUTYPE=ROOM;CN=LVM-E2.12:mailto:room@example.test\n"
        "RESOURCES:LVM-E2.14",
        location="-",
    )
    hints = inspect_ics_room_hints(ics)
    assert hints["events"] == 1
    assert hints["source_has_room_hints"] is True
    assert hints["room_property_counts"]["ATTENDEE"] == 1
    assert hints["room_property_counts"]["RESOURCES"] == 1
    assert "LVM-E2.12" in hints["room_candidates"]
    assert "LVM-E2.14" in hints["room_candidates"]
    assert "aventus.myx.nl" not in str(hints)


def test_v10_1_datumalarm_is_eenmalig_en_keert_niet_dagelijks_terug():
    settings = Settings.from_dict(
        {
            "alarm": {
                "alarms": [
                    {
                        "id": "presentatie",
                        "time": "07:05",
                        "date": "2026-10-03",
                        "enabled": True,
                    }
                ]
            }
        }
    )
    clock = FakeClock(datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc))
    core = AlarmClock(settings, clock, MockSpeaker(), MockLamp())

    assert core.next_alarm() == datetime(
        2026, 10, 3, 7, 5, tzinfo=timezone.utc
    )
    clock.set(datetime(2026, 10, 3, 7, 5, tzinfo=timezone.utc))
    assert core.tick() is AlarmState.RINGING
    assert core.dismiss(physical=True)

    clock.set(datetime(2026, 10, 4, 7, 0, tzinfo=timezone.utc))
    core.tick()
    assert core.next_alarm() is None


def test_v10_1_datumalarm_roundtrip_en_validatie():
    settings = Settings.from_dict(
        {
            "alarm": {
                "alarms": [
                    {
                        "id": "eenmalig",
                        "time": "08:15",
                        "date": "2026-10-31",
                        "enabled": True,
                    }
                ]
            }
        }
    )
    assert settings.alarm.alarms[0].date == "2026-10-31"
    restored = Settings.from_dict(settings.to_dict())
    assert restored.alarm.alarms[0].date == "2026-10-31"

    import pytest
    from wekker.settings import SettingsError

    with pytest.raises(SettingsError):
        Settings.from_dict(
            {
                "alarm": {
                    "alarms": [
                        {
                            "id": "fout",
                            "time": "08:15",
                            "date": "2026-02-31",
                            "enabled": True,
                        }
                    ]
                }
            }
        )


def test_v10_1_demo_sneltoets_en_pi_veilige_liquid_motion_zijn_aanwezig():
    source = (
        Path(__file__).parents[2] / "src" / "wekker" / "gui" / "app.py"
    ).read_text(encoding="utf-8")
    assert 'if keysym == "p":' in source
    assert '145 if effect == "liquid_motion" else 90' in source
    assert "splinesteps=8" in source
    assert "frame wordt veilig overgeslagen" in source


def test_v10_1_liquid_motion_renderframe_blijft_in_eventloop():
    from types import SimpleNamespace
    from wekker.gui.app import TouchApp

    class Canvas:
        def __init__(self):
            self.lines = 0
        def delete(self, *_args):
            return None
        def create_line(self, *_args, **_kwargs):
            self.lines += 1
            return self.lines
        def tag_lower(self, *_args):
            return None

    class Root:
        def __init__(self):
            self.after_calls = []
        def after(self, delay, callback):
            self.after_calls.append((delay, callback))
            return "after-1"

    app = TouchApp.__new__(TouchApp)
    app._sleeping = True
    app._sleep_animation_job = None
    app._sleep_phase = 0.0
    app._sleep_render_failures = 0
    app._widgets = {"_overlay_sleep_canvas": Canvas()}
    app._root = Root()
    app._runtime = SimpleNamespace(
        ctx=SimpleNamespace(
            settings=Settings().update_from_dict(
                {"display": {"sleep_effect": "liquid_motion"}}
            )
        )
    )

    app._animate_sleep_glow()
    assert app._widgets["_overlay_sleep_canvas"].lines == 8
    assert app._root.after_calls[0][0] == 145
    assert app._sleep_render_failures == 0


def test_v10_1_liquid_motion_renderfout_blokkeert_sleep_niet():
    from types import SimpleNamespace
    from wekker.gui.app import TouchApp

    class BrokenCanvas:
        def delete(self, *_args):
            return None
        def create_line(self, *_args, **_kwargs):
            raise RuntimeError("gesimuleerde renderfout")
        def tag_lower(self, *_args):
            return None

    class Root:
        def __init__(self):
            self.after_calls = []
        def after(self, delay, callback):
            self.after_calls.append((delay, callback))
            return "after-error"

    app = TouchApp.__new__(TouchApp)
    app._sleeping = True
    app._sleep_animation_job = None
    app._sleep_phase = 0.0
    app._sleep_render_failures = 0
    app._widgets = {"_overlay_sleep_canvas": BrokenCanvas()}
    app._root = Root()
    app._runtime = SimpleNamespace(
        ctx=SimpleNamespace(
            settings=Settings().update_from_dict(
                {"display": {"sleep_effect": "liquid_motion"}}
            )
        )
    )

    app._animate_sleep_glow()
    assert app._sleep_render_failures == 1
    assert app._root.after_calls[0][0] == 145
