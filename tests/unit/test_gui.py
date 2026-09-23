"""Tests: touchscreen-schermen en navigatie (headless, zonder tkinter)."""

from datetime import datetime, timedelta, timezone

import pytest

from wekker.agenda.cache import AgendaCache
from wekker.agenda.models import Lesson
from wekker.gui.screens import (
    AGENDA_MAX_ROWS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    AgendaScreenData,
    MainScreenData,
    Navigator,
    ScreenId,
    agenda_layout,
    build_agenda_data,
    build_main_data,
    format_alarm,
    format_time,
    layout_for,
    main_layout,
)


def _les(uur, minuut=0, vak="Wiskunde", source="mock"):
    tz = timezone.utc
    s = datetime(2026, 9, 14, uur, minuut, tzinfo=tz)
    return Lesson(subject=vak, start=s, end=s + timedelta(minutes=50), source=source)


def test_schermresolutie_is_800x480():
    assert (SCREEN_WIDTH, SCREEN_HEIGHT) == (800, 480)


def test_navigator_links_rechts_met_wrap():
    nav = Navigator()
    assert nav.current is ScreenId.MAIN
    assert nav.go_right() is ScreenId.AGENDA
    assert nav.go_right() is ScreenId.SETTINGS
    assert nav.go_right() is ScreenId.MAIN  # wrap
    assert nav.go_left() is ScreenId.SETTINGS
    assert nav.go_left() is ScreenId.AGENDA
    assert nav.go_left() is ScreenId.MAIN


def test_navigator_is_uitbreidbaar():
    nav = Navigator()
    nav.register(ScreenId.AGENDA)  # dubbel registreren is onschadelijk
    assert nav.go_right() is ScreenId.AGENDA
    with pytest.raises(ValueError):
        Navigator([])


def test_format_helpers():
    moment = datetime(2026, 9, 14, 7, 32, tzinfo=timezone.utc)
    assert format_time(moment) == "07:32"
    assert format_alarm(moment) == "07:32"
    assert format_alarm(None) == "uit"


def test_main_layout_toont_tijd_en_alarm_met_pijlen():
    layout = main_layout(MainScreenData(time_str="07:32", alarm_str="07:30"))
    assert layout["screen"] == "main"
    assert layout["time"] == "07:32"
    assert layout["alarm"] == "07:30"
    assert layout["left"] == {"label": "<", "target": "settings"}
    assert layout["right"] == {"label": ">", "target": "agenda"}


def test_agenda_layout_met_lessen_en_badge():
    lessen = [_les(9), _les(11, vak="Nederlands"), _les(13, 15, vak="Project")]
    data = build_agenda_data(lessen, provider_name="OSIRIS")
    layout = agenda_layout(data)
    assert layout["title"] == "OSIRIS"
    assert layout["day"] == "Vandaag"
    assert [r["time"] for r in layout["rows"]] == ["09:00", "11:00", "13:15"]
    assert [r["end"] for r in layout["rows"]] == ["09:50", "11:50", "14:05"]
    assert [r["subject"] for r in layout["rows"]] == ["Wiskunde", "Nederlands", "Project"]
    assert layout["simulated"] is True
    assert layout["empty_text"] == ""
    assert layout["left"]["target"] == "main"


def test_agenda_layout_leeg_en_limiet():
    leeg = agenda_layout(build_agenda_data([], provider_name="OSIRIS"))
    assert leeg["rows"] == []
    assert leeg["empty_text"] == "Geen lessen op deze dag"
    assert leeg["simulated"] is True
    veel = [_les(8 + i // 2, (i % 2) * 30, vak=f"Vak{i}") for i in range(8)]
    beperkt = agenda_layout(build_agenda_data(veel, provider_name="OSIRIS"))
    assert len(beperkt["rows"]) == AGENDA_MAX_ROWS


def test_agenda_layout_echte_data_zonder_badge():
    lessen = [_les(9, source="osiris")]
    layout = agenda_layout(build_agenda_data(lessen, provider_name="OSIRIS"))
    assert layout["simulated"] is False


def test_layout_for_volgt_navigator():
    data_main = MainScreenData(time_str="07:32", alarm_str="07:30")
    from wekker.gui.screens import GuiData

    data = GuiData(main=data_main, agenda=AgendaScreenData(
        provider_name="OSIRIS", day_label="Vandaag"))
    nav = Navigator()
    assert layout_for(nav, data)["screen"] == "main"
    nav.go_right()
    layout = layout_for(nav, data)
    assert layout["screen"] == "agenda"
    assert layout["title"] == "OSIRIS"
    nav.go_right()
    assert layout_for(nav, data)["screen"] == "settings"


def test_gui_data_uit_runtime(tmp_path):
    from wekker.main import build_default

    rt = build_default(tmp_path / "s.json")
    from wekker.gui.app import build_gui_data

    data = build_gui_data(rt)
    assert len(data.main.time_str) == 5  # HH:MM
    assert data.agenda.provider_name == "Mock (voorbeeldgegevens)"


def test_12_uurs_weergave_en_datumlabel():
    from datetime import date
    from wekker.gui.screens import format_day_label

    moment = datetime(2026, 7, 20, 20, 41, tzinfo=timezone.utc)
    assert format_time(moment, "12h") == "8:41 PM"
    assert format_time(moment, "24h") == "20:41"
    assert format_day_label(date(2026, 7, 20), date(2026, 7, 20)) == "Vandaag - 20 juli"
    assert format_day_label(date(2026, 7, 21), date(2026, 7, 20)) == "Dinsdag - 21 juli"


def test_agenda_regel_toont_eindtijd_lokaal_en_docent():
    tz = timezone.utc
    start = datetime(2026, 9, 14, 10, 30, tzinfo=tz)
    les = Lesson(
        subject="Netwerkbeheer",
        start=start,
        end=start + timedelta(minutes=90),
        teacher="Borl",
        room="KAM1",
        source="myx",
    )
    layout = agenda_layout(build_agenda_data([les], provider_name="MyX / Xedule"))
    row = layout["rows"][0]
    assert row["start"] == "10:30"
    assert row["end"] == "12:00"
    assert row["room"] == "KAM1"
    assert row["teacher"] == "Borl"
