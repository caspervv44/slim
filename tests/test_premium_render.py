"""Regressietests voor de puur grafische Premium-renderlaag."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from wekker.gui.premium_render import (
    HitTarget, PALETTES, THEME_TITLES, WIDTH, HEIGHT, render_screen,
)

ASSETS = Path(__file__).resolve().parents[1] / "src/wekker/assets"
MOMENT = datetime(2026, 10, 12, 7, 30)


@pytest.fixture
def layouts():
    return [
        {"screen": "main", "time": "07:30", "alarm": "08:15",
         "lesson_subject": "Wiskunde", "lesson_room": "B1.12",
         "lesson_time": "08:15 - 09:00", "alarm_day": "Morgen"},
        {"screen": "agenda", "day": "Vandaag - 12 oktober", "rows": [
            {"start": "08:15", "end": "09:00", "subject": "Wiskunde",
             "room": "B1.12", "teacher": "Mw. Janssen", "current": True},
        ], "page_count": 1, "page": 0, "total_rows": 1},
        {"screen": "alarm", "time": "07:30", "_clock_time": "07:31", "items": [
            {"id": "school", "time": "08:15", "enabled": True,
             "day_label": "Vandaag", "snooze_minutes": 9,
             "speaker_enabled": True, "lamp_blink": False},
        ]},
        {"screen": "settings", "timezone": "Europe/Amsterdam", "time_format": "24h",
         "sleep_after_seconds": 60, "sleep_glow_intensity": 65},
    ]


@pytest.mark.parametrize("theme", list(PALETTES))
@pytest.mark.parametrize("page_index", list(range(4)))
def test_alle_schermen_renderen_met_werkende_raakvlakken(theme, page_index, layouts):
    image, hits = render_screen(layouts[page_index], theme, MOMENT, ASSETS)
    assert image.size == (WIDTH,HEIGHT)
    assert image.mode == "RGB"
    assert len(hits) >= 4
    assert any(hit.action == "nav" for hit in hits)
    assert all(
        0 <= hit.x0 < hit.x1 <= WIDTH and 0 <= hit.y0 < hit.y1 <= HEIGHT
        for hit in hits
    )


def test_thema_sleutels_compatibel_met_vorige_wakesync():
    assert set(THEME_TITLES) == {"midnight","ocean","light","amber"}


def test_alarmen_hebben_tapbare_opties(layouts):
    _, hits = render_screen(layouts[2], "amber", MOMENT, ASSETS)
    for action in ("new-alarm","select-alarm","toggle-alarm",
                   "toggle-speaker","toggle-lamp","cycle-snooze"):
        assert any(hit.action == action for hit in hits)


def test_agenda_paginering(layouts):
    agenda = dict(layouts[1])
    agenda["page_count"] = 3
    agenda["page"] = 1
    _, hits = render_screen(agenda, "midnight", MOMENT, ASSETS)
    assert {h.payload for h in hits if h.action == "agenda-page"} == {"-1","1"}


def test_tikken_is_halfopen_interval():
    hit=HitTarget(10,20,30,40,"nav","alarm")
    assert hit.contains(10,20)
    assert hit.contains(29,39)
    assert not hit.contains(30,40)


def test_onbekend_thema_krijgt_veilige_fallback(layouts):
    result,_=render_screen(layouts[0],"geen-thema",MOMENT,ASSETS)
    assert result.size==(800,480)


def test_geen_logobestand_wordt_overschreven(layouts,tmp_path):
    logo=tmp_path/"wakesync-logo.png"
    logo.write_bytes(b"Dit is geen echte afbeelding")
    origineel=logo.read_bytes()
    render_screen(layouts[0],"light",MOMENT,ASSETS,logo_path=logo)
    assert logo.read_bytes()==origineel
