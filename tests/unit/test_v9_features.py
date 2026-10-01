from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from wekker.agenda.models import Lesson
from wekker.agenda.myx import parse_ics
from wekker.clock import SystemClock
from wekker.gui.app import TouchApp
from wekker.gui.screens import (
    AGENDA_PAGE_SIZE,
    AlarmScreenData,
    GuiData,
    MainScreenData,
    AgendaScreenData,
    Navigator,
    ScreenId,
    SettingsScreenData,
    build_agenda_data,
    build_main_data,
    build_main_data,
    layout_for,
)
from wekker.settings import Settings

TZ = ZoneInfo("Europe/Amsterdam")


def _lesson(day: date, hour: int, minute: int, end_hour: int, end_minute: int, subject: str) -> Lesson:
    return Lesson(
        subject=subject,
        start=datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ),
        end=datetime(day.year, day.month, day.day, end_hour, end_minute, tzinfo=TZ),
        source="myx",
    )


def test_agenda_houdt_laatste_les_1530_1700_op_eerste_pagina_bij_vijf_lessen():
    """Regressie: v8 maakte bij >4 lessen een tweede pagina die makkelijk werd gemist."""
    day = date(2026, 10, 1)
    lessons = [
        _lesson(day, 8, 30, 9, 45, "Project"),
        _lesson(day, 10, 0, 11, 15, "Project"),
        _lesson(day, 11, 30, 12, 45, "Project"),
        _lesson(day, 13, 30, 15, 15, "Project"),
        _lesson(day, 15, 30, 17, 0, "Project"),
    ]
    data = build_agenda_data(
        lessons,
        "MyX / Xedule",
        page=0,
        now=datetime(2026, 10, 1, 16, 0, tzinfo=TZ),
        loaded=True,
    )
    assert AGENDA_PAGE_SIZE >= 5
    assert data.page_count == 1
    assert data.total_rows == 5
    assert data.rows[-1].start_str == "15:30"
    assert data.rows[-1].end_str == "17:00"
    assert data.rows[-1].subject == "Project"
    assert data.rows[-1].current


def test_myx_location_placeholder_streepje_zoekt_door_in_description():
    ics = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:test-room-dash
DTSTART;TZID=W. Europe Standard Time:20261001T153000
DTEND;TZID=W. Europe Standard Time:20261001T170000
SUMMARY:Project
LOCATION:-
DESCRIPTION:KAMJ\\nLVM-E2.12 / E2.14 - LVM\\n533LVM6A-1A
END:VEVENT
END:VCALENDAR
"""
    lessons = parse_ics(ics)
    assert len(lessons) == 1
    assert lessons[0].room == "LVM-E2.12 / E2.14"


def test_myx_location_placeholder_em_dash_zoekt_door_in_html_vendorveld():
    ics = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:test-room-html
DTSTART:20261001T133000
DTEND:20261001T150000
SUMMARY:Project
LOCATION:—
DESCRIPTION:Projectles
X-ALT-DESC;FMTTYPE=text/html:<div>Docent KAMJ<br>LVM E3.07 - LVM</div>
END:VEVENT
END:VCALENDAR
"""
    lessons = parse_ics(ics)
    assert lessons[0].room == "LVM-E3.07"



def test_myx_lokaal_stroomt_van_ics_naar_vandaag_en_agenda():
    """End-to-end regressie voor de locatiebug uit v8.

    Xedule kan LOCATION als '-' invullen terwijl het echte lokaal in de HTML-
    beschrijving staat. Het lokaal moet na parsing zowel op Vandaag als in
    Agenda terechtkomen.
    """
    ics = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:project-1530
DTSTART;TZID=W. Europe Standard Time:20261001T153000
DTEND;TZID=W. Europe Standard Time:20261001T170000
SUMMARY:Project
LOCATION:-
DESCRIPTION:Projectles
X-ALT-DESC;FMTTYPE=text/html:<div>KAMJ<br>LVM-E2.12 / E2.14 - LVM<br>533LVM6A-1A</div>
END:VEVENT
END:VCALENDAR
"""
    lessons = parse_ics(ics)
    assert len(lessons) == 1
    assert lessons[0].room == "LVM-E2.12 / E2.14"

    now = datetime(2026, 10, 1, 16, 0, tzinfo=lessons[0].start.tzinfo)
    main = build_main_data(now, None, lessons=lessons, agenda_loaded=True)
    assert main.lesson_subject == "Project"
    assert main.lesson_room == "LVM-E2.12 / E2.14"

    agenda = build_agenda_data(
        lessons, "MyX / Xedule", now=now, loaded=True
    )
    assert agenda.rows[0].room == "LVM-E2.12 / E2.14"
    assert agenda.rows[0].start_str == "15:30"
    assert agenda.rows[0].end_str == "17:00"

def test_alarm_is_een_eigen_navigatietab():
    nav = Navigator()
    assert nav.current is ScreenId.MAIN
    assert nav.go_right() is ScreenId.AGENDA
    assert nav.go_right() is ScreenId.ALARM
    assert nav.go_right() is ScreenId.SETTINGS

    data = GuiData(
        main=MainScreenData("07:00", "07:30"),
        agenda=AgendaScreenData("MyX", "Vandaag"),
        alarm=AlarmScreenData(time="06:45", snooze_minutes=10),
        settings=SettingsScreenData(),
    )
    nav.go(ScreenId.ALARM)
    layout = layout_for(nav, data)
    assert layout["screen"] == "alarm"
    assert layout["time"] == "06:45"
    assert layout["snooze_minutes"] == 10


def test_360_graden_kiezer_mappt_boven_rechts_onder_links():
    # Het uurwiel heeft 24 gelijke sectoren: 00:00 boven, 06 rechts,
    # 12 onder, 18 links.
    value = TouchApp._angle_value
    assert value(143, 29, 143, 129, 24) == 0
    assert value(243, 129, 143, 129, 24) == 6
    assert value(143, 229, 143, 129, 24) == 12
    assert value(43, 129, 143, 129, 24) == 18

    # Minuten gebruiken dezelfde 360°-logica.
    assert value(143, 29, 143, 129, 60) == 0
    assert value(243, 129, 143, 129, 60) == 15
    assert value(143, 229, 143, 129, 60) == 30
    assert value(43, 129, 143, 129, 60) == 45


def test_slaapglow_instellingen_valideren_en_roundtrippen():
    settings = Settings()
    changed = settings.update_from_dict(
        {"display": {"sleep_effect": "aurora", "sleep_glow_intensity": 75}}
    )
    assert changed.display.sleep_effect == "aurora"
    assert changed.display.sleep_glow_intensity == 75
    restored = Settings.from_dict(changed.to_dict())
    assert restored.display.sleep_effect == "aurora"
    assert restored.display.sleep_glow_intensity == 75


def test_systemclock_gebruikt_lokale_systeemklok_zonder_netwerkdependency():
    clock = SystemClock("Europe/Amsterdam")
    first = clock.now()
    second = clock.now()
    assert first.tzinfo is not None
    assert second >= first
    assert getattr(clock, "timezone_name") == "Europe/Amsterdam"


def test_myx_generieke_campus_location_blokkeert_specifiek_lokaal_niet():
    ics = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:test-room-campus
DTSTART;TZID=W. Europe Standard Time:20261001T153000
DTEND;TZID=W. Europe Standard Time:20261001T170000
SUMMARY:Project
LOCATION:LVM
DESCRIPTION:Project\\nLVM-E2.12 / E2.14 - LVM\\nDocent: KAMJ
END:VEVENT
END:VCALENDAR
"""
    lessons = parse_ics(ics)
    assert lessons[0].room == "LVM-E2.12 / E2.14"


def test_lokaal_komt_end_to_end_op_vandaag_en_agenda():
    ics = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:test-room-e2e
DTSTART;TZID=W. Europe Standard Time:20261001T153000
DTEND;TZID=W. Europe Standard Time:20261001T170000
SUMMARY:Project
LOCATION:-
DESCRIPTION:Docent: KAMJ\\nLVM-E2.12 / E2.14 - LVM
END:VEVENT
END:VCALENDAR
"""
    lessons = parse_ics(ics)
    now = datetime(2026, 10, 1, 16, 0, tzinfo=TZ)

    main = build_main_data(
        now,
        None,
        lessons=lessons,
        agenda_loaded=True,
        agenda_status="Bijgewerkt",
    )
    agenda = build_agenda_data(
        lessons,
        "MyX / Xedule",
        now=now,
        loaded=True,
    )

    assert main.lesson_subject == "Project"
    assert main.lesson_room == "LVM-E2.12 / E2.14"
    assert agenda.rows[0].room == "LVM-E2.12 / E2.14"
    assert agenda.rows[0].start_str == "15:30"
    assert agenda.rows[0].end_str == "17:00"


def test_touch_setup_is_geen_product_cli_meer():
    source = (__import__("pathlib").Path(__file__).parents[2] / "src" / "wekker" / "main.py").read_text(
        encoding="utf-8"
    )
    assert 'sub.add_parser("touch-setup"' not in source
