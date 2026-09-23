"""Tests voor MyX/Xedule ICS-provider."""

from __future__ import annotations

import urllib.error
from datetime import date, datetime, timezone

import pytest

from wekker.agenda.cache import AgendaCache
from wekker.agenda.myx import (
    ENV_MYX_ATT_ID,
    ENV_MYX_BEARER_TOKEN,
    MyXAgendaProvider,
    MyXConfig,
    parse_ics,
)
from wekker.agenda.providers import ProviderError
from wekker.agenda.sync import AgendaSyncService
from wekker.clock import FakeClock


ICS_TWO = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:1
SUMMARY:Project
DTSTART;TZID=W. Europe Standard Time:20260917T133000
DTEND;TZID=W. Europe Standard Time:20260917T150000
LOCATION:A1.23
DESCRIPTION:Docent: Mevrouw Test\\nGroep: G1
END:VEVENT
BEGIN:VEVENT
UID:2
SUMMARY:Service Management
DTSTART;TZID=W. Europe Standard Time:20260917T153000
DTEND;TZID=W. Europe Standard Time:20260917T163000
LOCATION:B2.04
END:VEVENT
END:VCALENDAR
"""


def test_ics_parsing_meerdere_lessen_en_velden():
    lessen = parse_ics(ICS_TWO)
    assert [les.subject for les in lessen] == ["Project", "Service Management"]
    assert lessen[0].start.hour == 13
    assert lessen[0].start.minute == 30
    assert lessen[0].end.hour == 15
    assert lessen[0].room == "A1.23"
    assert lessen[0].teacher == "Mevrouw Test"
    assert all(les.source == "myx" for les in lessen)



def test_lokaal_wordt_uit_ongelabelde_myx_description_gehaald():
    tekst = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Netwerkbeheer
DTSTART;TZID=W. Europe Standard Time:20260921T133000
DTEND;TZID=W. Europe Standard Time:20260921T150000
DESCRIPTION:KAMJ\\nLVM-E2.20 / E2.14 - LVM\\n533LVM6A-1C
END:VEVENT
END:VCALENDAR
"""
    les = parse_ics(tekst)[0]
    assert les.room == "LVM-E2.20 / E2.14"

def test_lege_geldige_agenda():
    assert parse_ics("BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n") == []


@pytest.mark.parametrize(
    "tekst",
    [
        "",
        "dit is geen ics",
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:X\nEND:VCALENDAR",
        (
            "BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:X\n"
            "DTSTART;TZID=W. Europe Standard Time:20260917T083000\n"
            "END:VEVENT\nEND:VCALENDAR"
        ),
    ],
)
def test_ongeldige_ics_geeft_provider_error(tekst):
    with pytest.raises(ProviderError):
        parse_ics(tekst)


def test_timezone_zomer_en_winter_dst():
    tekst = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Winter
DTSTART;TZID=W. Europe Standard Time:20260115T083000
DTEND;TZID=W. Europe Standard Time:20260115T093000
END:VEVENT
BEGIN:VEVENT
SUMMARY:Zomer
DTSTART;TZID=W. Europe Standard Time:20260715T083000
DTEND;TZID=W. Europe Standard Time:20260715T093000
END:VEVENT
END:VCALENDAR
"""
    lessen = parse_ics(tekst)
    winter, zomer = lessen
    assert winter.start.utcoffset().total_seconds() == 3600
    assert zomer.start.utcoffset().total_seconds() == 7200


def test_utc_tijden_worden_naar_amsterdam_omgezet():
    tekst = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:UTC-les
DTSTART:20260917T113000Z
DTEND:20260917T123000Z
END:VEVENT
END:VCALENDAR
"""
    les = parse_ics(tekst)[0]
    assert (les.start.hour, les.start.minute) == (13, 30)
    assert les.start.tzinfo is not None


def test_folded_lines_en_escaping():
    tekst = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Project\\, deel 1
DTSTART;TZID=W. Europe Standard Time:20260917T133000
DTEND;TZID=W. Europe Standard Time:20260917T143000
DESCRIPTION:Docent: Jan
 Jansen
LOCATION:A\\,1
END:VEVENT
END:VCALENDAR
"""
    les = parse_ics(tekst)[0]
    assert les.subject == "Project, deel 1"
    assert les.room == "A,1"


def test_config_alleen_env_namen_in_fout(monkeypatch):
    geheim = "super-geheime-token"
    monkeypatch.setenv(ENV_MYX_BEARER_TOKEN, geheim)
    monkeypatch.delenv(ENV_MYX_ATT_ID, raising=False)
    cfg = MyXConfig.from_env()
    assert not cfg.configured
    assert cfg.missing() == [ENV_MYX_ATT_ID]
    assert geheim not in str(cfg.missing())


class _Headers:
    def get_content_charset(self):
        return "utf-8"


class _Response:
    headers = _Headers()

    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_provider_stuurt_bearer_en_correct_datumbereik():
    gezien = {}

    def opener(request, timeout):
        gezien["url"] = request.full_url
        gezien["auth"] = request.get_header("Authorization")
        gezien["timeout"] = timeout
        return _Response(ICS_TWO.encode())

    provider = MyXAgendaProvider(
        MyXConfig(bearer_token="token123", att_id="123456"),
        opener=opener,
    )
    lessen = provider.fetch_day(date(2026, 9, 17))
    assert len(lessen) == 2
    assert "start=2026-09-17" in gezien["url"]
    assert "end=2026-09-18" in gezien["url"]
    assert "attId=123456" in gezien["url"]
    assert gezien["auth"] == "Bearer token123"


@pytest.mark.parametrize("status", [401, 403])
def test_authenticatiefout_is_duidelijk_en_lekt_token_niet(status):
    geheim = "zeer-geheim"

    def opener(request, timeout):
        raise urllib.error.HTTPError(request.full_url, status, "no", {}, None)

    provider = MyXAgendaProvider(
        MyXConfig(bearer_token=geheim, att_id="123456"),
        opener=opener,
    )
    with pytest.raises(ProviderError) as exc:
        provider.fetch_day(date(2026, 9, 17))
    assert "authenticatie" in str(exc.value).lower()
    assert geheim not in str(exc.value)


def test_api_netwerkfout_wordt_provider_error():
    def opener(request, timeout):
        raise urllib.error.URLError("offline")

    provider = MyXAgendaProvider(
        MyXConfig(bearer_token="token", att_id="123456"),
        opener=opener,
    )
    with pytest.raises(ProviderError) as exc:
        provider.fetch_day(date(2026, 9, 17))
    assert "niet bereikbaar" in str(exc.value)


def test_sync_failure_behoudt_oude_cache():
    klok = FakeClock(datetime(2026, 9, 17, 6, 0, tzinfo=timezone.utc))
    cache = AgendaCache()
    oude_les = parse_ics(ICS_TWO)[0]
    cache.put_day(date(2026, 9, 17), [oude_les])

    class FalendeProvider:
        name = "myx"
        sync_horizon_days = 21

        def fetch_range(self, start, end):
            raise ProviderError("tijdelijke fout")

        def fetch_day(self, day):
            raise ProviderError("tijdelijke fout")

    sync = AgendaSyncService(FalendeProvider(), cache, klok)
    assert sync.sync_default_window() is False
    assert cache.get_day(date(2026, 9, 17)) == [oude_les]
    assert cache.status == "error"


def test_range_sync_schrijft_ook_lege_dagen():
    klok = FakeClock(datetime(2026, 9, 17, 6, 0, tzinfo=timezone.utc))
    cache = AgendaCache()
    lessen = parse_ics(ICS_TWO)

    class RangeProvider:
        name = "myx"
        sync_horizon_days = 2

        def fetch_range(self, start, end):
            return lessen

        def fetch_day(self, day):
            raise AssertionError("fetch_day hoort niet gebruikt te worden")

    sync = AgendaSyncService(RangeProvider(), cache, klok)
    assert sync.sync_default_window() is True
    assert len(cache.get_day(date(2026, 9, 17))) == 2
    assert cache.get_day(date(2026, 9, 18)) == []


def test_provider_gebruikt_stabiele_feed_zonder_bearer():
    gezien = {}
    feed = (
        "https://aventus.myx.nl/api/InternetCalendar/feed/"
        "11111111-1111-4111-8111-111111111111/"
        "22222222-2222-4222-8222-222222222222"
    )

    def opener(request, timeout):
        gezien["url"] = request.full_url
        gezien["auth"] = request.get_header("Authorization")
        return _Response(ICS_TWO.encode())

    provider = MyXAgendaProvider(MyXConfig(feed_url=feed), opener=opener)
    lessen = provider.fetch_range(date(2026, 9, 17), date(2026, 9, 18))

    assert len(lessen) == 2
    assert gezien["url"] == feed
    assert gezien["auth"] is None
