#!/usr/bin/env python3
"""Maak de vier overzichtsbeelden van de werkelijke v10.2-renderlaag."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from wekker.gui.premium_render import (
    THEME_TITLES, render_screen, render_sleep_screen, render_detail_screen,
)

ASSETS = ROOT / "src/wekker/assets"
DEST = ROOT / "previews"
NOW = datetime(2026, 10, 12, 7, 30)

MOCK_ALARMS = [
    {
        "id": "school", "time": "07:30", "day_label": "Morgen",
        "enabled": True, "snooze_minutes": 10, "speaker_enabled": True,
        "lamp_blink": True, "sound": "beep", "volume": 70,
        "lamp_brightness": 100, "blink_pattern": "blink", "ramp_up_seconds": 30,
    },
    {
        "id": "studie", "time": "08:15", "day_label": "Vandaag",
        "enabled": True, "snooze_minutes": 5, "speaker_enabled": True,
        "lamp_blink": False,
    },
]

DEMO_SETTINGS = SimpleNamespace(
    display=SimpleNamespace(
        brightness=80, sleep_after_seconds=60, sleep_view="logo_time_date",
        sleep_effect="soft_glow", sleep_glow_intensity=65,
    ),
    locale=SimpleNamespace(timezone="Europe/Amsterdam", time_format="24h"),
)

LAYOUTS = [
    ("Vandaag", {
        "screen": "main", "time": "07:30", "alarm": "07:45",
        "alarm_day": "Morgen", "lesson_label": "VOLGENDE LES",
        "lesson_subject": "Wiskunde", "lesson_time": "08:15 – 09:00",
        "lesson_room": "B1.12", "lesson_teacher": "Mw. Janssen",
        "agenda_status": "Rooster bijgewerkt",
    }),
    ("Agenda", {
        "screen": "agenda", "day": "Vandaag – 12 oktober", "provider": "MyX",
        "rows": [
            {"start": start, "end": end, "subject": subject, "room": room,
             "teacher": "Docent", "current": idx == 1}
            for idx, (start, end, subject, room) in enumerate([
                ("08:15", "09:00", "Wiskunde", "B1.12"),
                ("09:05", "09:50", "Nederlands", "A1.04"),
                ("10:10", "10:55", "Engels", "B1.20"),
                ("11:05", "11:50", "Geschiedenis", "A0.18"),
                ("12:35", "13:20", "Biologie", "B3.01"),
                ("13:30", "14:15", "Informatica", "C1.15"),
            ])
        ], "page": 0, "page_count": 1, "total_rows": 6,
        "status_text": "Bijgewerkt", "simulated": True,
    }),
    ("Alarm", {
        "screen": "alarm", "_clock_time": "07:30",
        "items": MOCK_ALARMS,
    }),
    ("Instellingen", {
        "screen": "settings", "timezone": "Europe/Amsterdam",
        "time_format": "24h", "sleep_after_seconds": 60,
        "sleep_glow_intensity": 65, "cloud_status": "Klaar",
    }),
]


def _font(size: int, bold: bool = False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default()


def generate() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    for theme, title in THEME_TITLES.items():
        board = Image.new("RGB", (1240, 1280), "#111B2B" if theme != "light" else "#E9EDF3")
        painter = ImageDraw.Draw(board)
        text = "#F9FAFC" if theme != "light" else "#20344D"
        painter.text((36, 18), f"WakeSync 10.2   |   {title}", font=_font(32, True), fill=text)
        painter.text(
            (36, 62), "7 WEERGAVEN · DEMOGEGEVENS · 800 × 480 OP DE RASPBERRY PI",
            font=_font(14), fill=text,
        )
        for index, (label, layout) in enumerate(LAYOUTS):
            img, _hits = render_screen(layout, theme, NOW, ASSETS, ASSETS / "wakesync-logo.png")
            thumbnail = img.resize((550, 330), Image.Resampling.LANCZOS)
            x = 38 + (index % 2) * 594
            y = 105 + (index // 2) * 365
            painter.text((x, y), f"{index + 1:02d}   {label}",
                         font=_font(17, True), fill=text)
            board.paste(thumbnail, (x, y + 30))

        third_row = [
            ("Weergave-instellingen", render_detail_screen(
                "display", theme, NOW, ASSETS, settings=DEMO_SETTINGS,
            )[0]),
            ("Alarmdetails", render_detail_screen(
                "alarm", theme, NOW, ASSETS, item=MOCK_ALARMS[0],
            )[0]),
            ("Sleepscreen (P)", render_sleep_screen(
                theme, NOW.replace(hour=22, minute=30), ASSETS,
                logo_path=ASSETS / "wakesync-logo.png", view="logo_time_date",
            )),
        ]
        for index, (label, img) in enumerate(third_row):
            x = 35 + index * 403
            y = 850
            painter.text((x, y), f"{index + 5:02d}   {label}",
                         font=_font(16, True), fill=text)
            board.paste(img.resize((386, 232), Image.Resampling.LANCZOS), (x, y + 30))
        painter.text((38, 1155), "Vier themavarianten · echt gerenderde GUI-ontwerpen",
                     font=_font(14), fill=text)
        dest = DEST / f"{theme}-zeven-schermen.png"
        board.save(dest, optimize=True)
        print(dest)


if __name__ == "__main__":
    generate()
