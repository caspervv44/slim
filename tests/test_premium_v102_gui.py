"""Test dat de nieuwe premium-Canvas niet verwijderd wordt bij tabwissels.

Dit is een headless test met nep-Tk-widgets; het echte Raspberry Pi-touchdisplay
blijft nog apart te controleren.
"""
from __future__ import annotations

from datetime import datetime
import importlib.util
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]


class FakeCanvas:
    created: list["FakeCanvas"] = []

    def __init__(self, _frame, **kwargs):
        self.deleted = 0
        self.swap_count = 0
        self.create_count = 0
        self.kwargs = kwargs
        FakeCanvas.created.append(self)

    def winfo_exists(self):
        return True

    def pack(self, **kwargs):
        pass

    def bind(self, name, handler):
        self.handler = handler

    def create_image(self, *args, **kwargs):
        self.create_count += 1
        return self.create_count

    def itemconfigure(self, *_args, **_kwargs):
        self.swap_count += 1

    def delete(self, *_args):
        self.deleted += 1


def _load_module(monkeypatch):
    import tkinter as tk

    dummy=types.ModuleType("wekker.gui.app")
    dummy.THEME_CHOICES=()
    dummy.THEMES={x:{} for x in ("midnight","ocean","light","amber")}
    dummy.TouchApp=type("TouchApp",(),{})
    dummy.BG="#0a1421"
    dummy.format_time=lambda moment,fmt:moment.strftime("%H:%M")
    monkeypatch.setitem(sys.modules,"wekker.gui.app",dummy)
    import wekker.gui
    monkeypatch.setattr(wekker.gui,"app",dummy,raising=False)
    monkeypatch.setattr(tk,"Canvas",FakeCanvas)
    spec=importlib.util.spec_from_file_location(
        "_wakesync_premium_test",ROOT/"src/wekker/gui/premium.py",
    )
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.ImageTk,"PhotoImage",lambda _image,master=None:object())
    return module


def test_tabwissel_behoudt_canvas_en_vervangt_de_foto(monkeypatch):
    module=_load_module(monkeypatch)
    fake=module.PremiumTouchApp.__new__(module.PremiumTouchApp)
    FakeCanvas.created.clear()
    fake._widgets={}
    fake._frame=object()
    fake._root=object()
    fake._active_theme="midnight"
    fake._alarm_selected_id=None
    fake._alarm_list_page=0
    fake._premium_canvas_item=None
    fake._premium_render_key=None
    fake._premium_hits=[]
    fake._runtime=types.SimpleNamespace(ctx=types.SimpleNamespace(
        clock=types.SimpleNamespace(now=lambda:datetime(2026,10,12,7,30)),
        settings=types.SimpleNamespace(
            locale=types.SimpleNamespace(time_format="24h"),
        ),
    ))
    today={
        "screen":"main","time":"07:30","alarm":"07:45","alarm_day":"Morgen",
        "lesson_subject":"Wiskunde","lesson_time":"08:15 - 09:00",
        "agenda_status":"Bijgewerkt",
    }
    agenda={"screen":"agenda","day":"Vandaag","rows":[],"page_count":1}

    fake._rebuild(today)
    assert fake._screen=="main"
    assert len(FakeCanvas.created)==1
    canvas=FakeCanvas.created[0]
    assert canvas.create_count==1
    assert canvas.deleted==0

    # Zelfde scherm en dezelfde minuut => niet opnieuw renderen.
    fake._rebuild(today)
    assert canvas.swap_count==0

    fake._rebuild(agenda)
    assert fake._screen=="agenda"
    assert len(FakeCanvas.created)==1
    assert canvas.create_count==1
    assert canvas.swap_count==1
    assert canvas.deleted==0

