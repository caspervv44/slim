"""Tests voor privacyvriendelijke, alleen-lezen MyX-diagnostiek."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
import importlib.util
import io
from pathlib import Path
import sys
import types
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "diagnose_myx_rooster.py"


def load_tool(monkeypatch):
    fake_wekker = types.ModuleType("wekker")
    fake_agenda = types.ModuleType("wekker.agenda")
    fake_cache = types.ModuleType("wekker.agenda.cache")
    fake_myx = types.ModuleType("wekker.agenda.myx")
    fake_auth = types.ModuleType("wekker.agenda.myx_auth")

    class FakeCache:
        def __init__(self, path=None):
            self.path = path
        def get_day(self, day):
            return []
    class FakeFeedStore:
        def load(self):
            return "https://example.invalid/token-geheim"
    class FakeConfig:
        def __init__(self, feed_url):
            self.feed_url = feed_url
    class FakeProvider:
        def __init__(self, config):
            self.config = config
        def fetch_raw_ics(self, start, end):
            return ""
    class FakeLesson:
        def __init__(self, day):
            self.start = types.SimpleNamespace(date=lambda: day)

    def unfold(text):
        lines = []
        for row in text.replace("\r\n", "\n").split("\n"):
            if row.startswith((" ", "\t")) and lines:
                lines[-1] += row[1:]
            else:
                lines.append(row)
        return lines

    def split_prop(line):
        field, value = line.split(":", 1)
        items = field.split(";")
        params = dict(chunk.split("=",1) for chunk in items[1:] if "=" in chunk)
        return items[0].upper(), params, value

    def parse_dt(value, params):
        if len(value) == 8:
            return None
        dt = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
        return dt.replace(tzinfo=ZoneInfo("Europe/Amsterdam"))

    def parse_ics(text):
        # Fake parser emuleert de huidige parser: iedere VEVENT precies één les.
        dates = []
        for line in unfold(text):
            if line.startswith("DTSTART"):
                n, p, v = split_prop(line)
                dt = parse_dt(v, p)
                if dt is not None:
                    dates.append(FakeLesson(dt.date()))
        return dates

    fake_cache.AgendaCache = FakeCache
    fake_myx.MyXAgendaProvider = FakeProvider
    fake_myx.MyXConfig = FakeConfig
    fake_myx._unfold_ics = unfold
    fake_myx._split_property = split_prop
    fake_myx._parse_datetime = parse_dt
    fake_myx.parse_ics = parse_ics
    fake_auth.MyXFeedStore = FakeFeedStore

    for key, value in (
        ("wekker", fake_wekker), ("wekker.agenda", fake_agenda),
        ("wekker.agenda.cache", fake_cache), ("wekker.agenda.myx", fake_myx),
        ("wekker.agenda.myx_auth", fake_auth),
    ):
        monkeypatch.setitem(sys.modules, key, value)

    spec = importlib.util.spec_from_file_location("diagnose_myx_rooster_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module, FakeLesson


def test_dagregels_en_herhalingen(monkeypatch):
    tool, _ = load_tool(monkeypatch)
    ics = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\nDTSTART;TZID=Europe/Amsterdam:20261006T083000\r\n"
        "RRULE:FREQ=WEEKLY;BYDAY=TU\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nDTSTART;TZID=Europe/Amsterdam:20261013T100000\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    info = tool.analyseer_bron(ics, date(2026, 10, 12))
    assert info.evenementen == 2
    assert info.herhalingen == 1
    assert info.oude_herhalingen == 1
    assert info.startdatums[date(2026, 10, 13)] == 1


@pytest.mark.parametrize("source,parsed,cache,rrule,expected", [
    (1, 0, 0, 0, "PARSER"),
    (1, 1, 0, 0, "CACHE"),
    (0, 0, 0, 1, "HERHALINGEN"),
    (0, 0, 0, 0, "BRON"),
])
def test_diagnoselogica(monkeypatch, source, parsed, cache, rrule, expected):
    tool, _ = load_tool(monkeypatch)
    start = date(2026, 10, 12)
    target = date(2026, 10, 13)
    info = tool.BronAnalyse(
        1, Counter({target: source}), rrule, rrule, 0, 0, 0, 0, 0
    )
    text = tool.oordeel(info, Counter({target: parsed}),
                        Counter({target: cache}), start, 3)
    assert text.startswith(expected)


def test_geheim_nooit_in_uitvoer(monkeypatch, tmp_path, capsys):
    tool, FakeLesson = load_tool(monkeypatch)
    start = date(2026, 10, 12)
    class Store:
        def load(self):
            return "https://example.invalid/ZEERGEHEIM"
    class Provider:
        def __init__(self, config):
            self.config = config
        def fetch_raw_ics(self, start_date, end_date):
            assert "ZEERGEHEIM" in self.config.feed_url
            return (
                "BEGIN:VCALENDAR\nBEGIN:VEVENT\n"
                "SUMMARY:VERBORGEN VAK\n"
                "DTSTART;TZID=Europe/Amsterdam:20261013T083000\n"
                "DTEND;TZID=Europe/Amsterdam:20261013T093000\n"
                "END:VEVENT\nEND:VCALENDAR\n"
            )
    result = tool.onderzoek(
        tmp_path/"wekker-settings.json", start, 2,
        feed_store=Store(), provider_type=Provider
    )
    out = capsys.readouterr().out
    assert result == 0
    assert "2026-10-13" in out
    assert "ZEERGEHEIM" not in out
    assert "VERBORGEN VAK" not in out
    assert "080000" not in out
