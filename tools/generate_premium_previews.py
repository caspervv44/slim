#!/usr/bin/env python3
"""Maak voorbeeldborden van de ECHTE Pillow-renderer zonder toegang tot de Pi."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from wekker.gui.premium_render import render_screen, THEME_TITLES

ASSETS = ROOT/"src/wekker/assets"
DEST = ROOT/"previews"
MOMENT = datetime(2026,10,12,7,30)
ROWS = [
    ("08:15","09:00","Wiskunde","B1.12"),
    ("09:05","09:50","Nederlands","A1.04"),
    ("10:10","10:55","Engels","B1.20"),
    ("11:05","11:50","Geschiedenis","A0.18"),
    ("12:35","13:20","Biologie","B3.01"),
    ("13:30","14:15","Informatica","C1.15"),
]
LAYOUTS = [
    ("Vandaag",{
        "screen":"main","time":"07:30","alarm":"07:45",
        "alarm_day":"Morgen","lesson_label":"VOLGENDE LES",
        "lesson_subject":"Wiskunde","lesson_time":"08:15 - 09:00",
        "lesson_room":"B1.12","lesson_teacher":"Mw. Janssen",
        "agenda_status":"Rooster bijgewerkt",
    }),
    ("Agenda",{
        "screen":"agenda","day":"Vandaag - 12 oktober","provider":"MyX",
        "rows":[
            {"start":start,"end":end,"subject":subject,"room":room,
             "current":i==1}
            for i,(start,end,subject,room) in enumerate(ROWS)
        ],
        "total_rows":len(ROWS),"page":0,"page_count":1,
        "status_text":"Bijgewerkt om 07:12", "simulated":True,
    }),
    ("Alarm",{
        "screen":"alarm","_clock_time":"07:30","time":"07:30",
        "items":[
            {"id":"1","time":"07:30","day_label":"Morgen","enabled":True,
             "date":None,"snooze_minutes":10,"speaker_enabled":True,"lamp_blink":True},
            {"id":"2","time":"08:15","day_label":"Vandaag","enabled":True,
             "date":None,"snooze_minutes":5,"speaker_enabled":True,"lamp_blink":False},
            {"id":"3","time":"22:30","day_label":"13 okt","enabled":False,
             "date":"2026-10-13","snooze_minutes":9,
             "speaker_enabled":False,"lamp_blink":False},
        ],
    }),
    ("Instellingen",{
        "screen":"settings","timezone":"Europe/Amsterdam","time_format":"24h",
        "sleep_after_seconds":60,"sleep_glow_intensity":65,"cloud_status":"Verbonden",
    }),
]


def generate() -> None:
    DEST.mkdir(exist_ok=True)
    for theme,title in THEME_TITLES.items():
        board=Image.new("RGB",(1180,810),(13,19,29) if theme!="light" else (237,241,246))
        draw=ImageDraw.Draw(board)
        color="#FFFFFF" if theme!="light" else "#21344D"
        try:
            font=ImageFont.truetype("DejaVuSans-Bold.ttf",31)
            label_font=ImageFont.truetype("DejaVuSans-Bold.ttf",17)
            small_font=ImageFont.truetype("DejaVuSans.ttf",12)
        except OSError:
            font=label_font=small_font=ImageFont.load_default()
        draw.text((31,15),f"WAKE SYNC  ·  {title}",font=font,fill=color)
        draw.text((34,57),"ONTWERPVOORBEELD  ·  FICTIEVE DEMOGEGEVENS",font=small_font,fill=color)
        for idx,(name,layout) in enumerate(LAYOUTS):
            screenshot,_=render_screen(layout,theme,MOMENT,ASSETS,
                                       ASSETS/"wakesync-logo.png")
            preview=screenshot.resize((550,330),Image.Resampling.LANCZOS)
            x=28+(idx%2)*579
            y=92+(idx//2)*355
            board.paste(preview,(x,y+22))
            draw.text((x,y-1),f"{idx+1:02d}  {name}",fill=color,font=label_font)
        board.save(DEST/f"{theme}-vier-schermen.png",optimize=True)
        print(f"Voorbeeld: {DEST/(theme+'-vier-schermen.png')}")


if __name__ == "__main__":
    generate()
