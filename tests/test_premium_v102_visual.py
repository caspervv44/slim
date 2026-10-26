"""Controleer thema-details, sleepscreens en placeholderdata zonder Raspberry Pi."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import types

import pytest

from wekker.gui.premium_render import (
    PALETTES, render_detail_screen, render_screen, render_sleep_screen,
)

ASSETS = Path(__file__).resolve().parents[1] / "src/wekker/assets"
NOW = datetime(2026, 10, 12, 22, 30)


def demo_settings():
    return types.SimpleNamespace(
        locale=types.SimpleNamespace(timezone="Europe/Amsterdam", time_format="24h"),
        display=types.SimpleNamespace(
            sleep_after_seconds=60,
            sleep_view="logo_time_date",
            sleep_effect="soft_glow",
            sleep_glow_intensity=65,
            brightness=80,
        ),
    )


@pytest.mark.parametrize("theme", list(PALETTES))
def test_premium_weergaveinstellingen_per_thema(theme):
    picture, hits = render_detail_screen(
        "display", theme, NOW, ASSETS, settings=demo_settings(),
    )
    assert picture.size == (800, 480)
    actions = {x.action for x in hits}
    assert {"theme", "time-format", "next-sleep-after", "next-sleep-view",
            "next-sleep-effect", "next-glow", "next-brightness", "close-detail",
            "preview-sleep"} <= actions


@pytest.mark.parametrize("theme", list(PALETTES))
def test_premium_alarmdetails_per_thema(theme):
    alarm = {
        "id": "test", "time": "06:15", "enabled": True, "day_label": "Morgen",
        "snooze_minutes": 9, "sound": "beep", "speaker_enabled": True,
        "lamp_blink": True, "volume": 65, "lamp_brightness": 80,
        "blink_pattern": "pulse", "ramp_up_seconds": 30,
    }
    image, hits = render_detail_screen("alarm", theme, NOW, ASSETS, item=alarm)
    assert image.mode == "RGB"
    assert all(x.contains((x.x0 + x.x1 - 1)//2,(x.y0 + x.y1 - 1)//2) for x in hits)
    actions = {x.action for x in hits}
    assert {"alarm-enabled", "alarm-snooze", "alarm-sound", "alarm-speaker",
            "alarm-volume", "alarm-ramp", "test-audio", "alarm-delete"} <= actions
    assert not {"alarm-lamp", "alarm-lamp-brightness", "alarm-pattern"} & actions


@pytest.mark.parametrize("theme", list(PALETTES))
@pytest.mark.parametrize("view", ["logo", "logo_time", "logo_time_date"])
def test_sleepscreen_thematisch(theme, view):
    image = render_sleep_screen(theme, NOW, ASSETS, view=view, glow=70)
    assert image.size == (800, 480)
    assert image.mode == "RGB"


def test_geen_quotes_of_verzonnen_temperatuur():
    import inspect
    from wekker.gui import premium_render
    source = inspect.getsource(premium_render._draw_today)
    assert "TEMPERATUUR" in source
    assert '"--"' in source
    for quote in ("rustig beginnen", "sterk eindigen", "nieuwe kansen", "dag in balans"):
        assert quote not in source.lower()


def test_sleepscreen_ongeldige_view_blijft_geldig():
    img = render_sleep_screen("midnight", NOW, ASSETS, view="onbekend", glow=0)
    assert img.size == (800,480)


def test_render_detail_type_en_verplichte_data():
    with pytest.raises(ValueError):
        render_detail_screen("niet-bestaand", "midnight", NOW, ASSETS)
    with pytest.raises(ValueError):
        render_detail_screen("alarm", "midnight", NOW, ASSETS)

