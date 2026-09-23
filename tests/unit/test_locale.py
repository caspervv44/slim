"""Tests: locale-instellingen (timezone/region) en DST-gedrag.

De wekker draait op Europe/Amsterdam; zomertijd/wintertijd wordt volledig
door zoneinfo afgehandeld (nergens een hardcoded UTC-offset).
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from wekker.settings import (
    DEFAULT_REGION,
    DEFAULT_TIMEZONE,
    Settings,
    SettingsError,
    default_settings,
)


def test_locale_defaults_zijn_amsterdam_nl():
    s = default_settings()
    assert s.locale.timezone == DEFAULT_TIMEZONE == "Europe/Amsterdam"
    assert s.locale.region == DEFAULT_REGION == "NL"


def test_locale_timezone_moet_bij_zoneinfo_bestaan():
    assert Settings.from_dict({"locale": {"timezone": "Europe/Amsterdam"}}).locale.timezone == \
        "Europe/Amsterdam"
    for fout in ("UTC+1", "Amsterdam", "Europe/Atlantis", "", 1):
        with pytest.raises(SettingsError):
            Settings.from_dict({"locale": {"timezone": fout}})


def test_locale_region_is_iso_landcode():
    assert Settings.from_dict({"locale": {"region": "nl"}}).locale.region == "NL"
    for fout in ("Nederland", "N", "NLD", "1A", ""):
        with pytest.raises(SettingsError):
            Settings.from_dict({"locale": {"region": fout}})


def test_locale_update_is_atomair_en_rondtrip():
    s = default_settings()
    nieuwe = s.update_from_dict({"locale": {"timezone": "Europe/Amsterdam", "region": "NL"}})
    assert nieuwe.locale.timezone == "Europe/Amsterdam"
    assert s.locale.timezone == "Europe/Amsterdam"  # ongewijzigd object blijft geldig
    with pytest.raises(SettingsError):
        s.update_from_dict({"locale": {"timezone": "UTC+1"}})
    assert s.locale.timezone == "Europe/Amsterdam"
    assert Settings.from_dict(s.to_dict()).to_dict() == s.to_dict()


def test_amsterdam_dst_winter_plus1_zomer_plus2():
    ams = ZoneInfo("Europe/Amsterdam")
    winter = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc).astimezone(ams)
    zomer = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc).astimezone(ams)
    assert winter.utcoffset() == timedelta(hours=1)
    assert zomer.utcoffset() == timedelta(hours=2)
    assert winter.tzname() == "CET"
    assert zomer.tzname() == "CEST"


def test_alarm_gebruikt_lokale_zone_zonder_harde_offset():
    """Dezelfde wektijd valt in winter en zomer op verschillende UTC-tijden."""
    from wekker.alarm.core import AlarmClock
    from wekker.clock import FakeClock
    from wekker.hardware.mock import MockLamp, MockSpeaker

    ams = ZoneInfo("Europe/Amsterdam")
    for moment, verwachte_utc in (
        (datetime(2026, 1, 15, 6, 0, tzinfo=ams), datetime(2026, 1, 15, 6, 30,
                                                          tzinfo=timezone.utc)),
        (datetime(2026, 7, 15, 6, 0, tzinfo=ams), datetime(2026, 7, 15, 5, 30,
                                                          tzinfo=timezone.utc)),
    ):
        s = default_settings()
        klok = FakeClock(moment)
        core = AlarmClock(s, klok, MockSpeaker(), MockLamp())
        nxt = core.next_alarm()
        assert nxt is not None
        assert nxt.astimezone(timezone.utc) == verwachte_utc


def test_systemclock_is_timezone_aware():
    from wekker.clock import SystemClock

    now = SystemClock().now()
    assert now.tzinfo is not None
    assert now.utcoffset() is not None


def test_tijdformaat_wordt_gevalideerd():
    assert default_settings().locale.time_format == "24h"
    assert Settings.from_dict({"locale": {"time_format": "12h"}}).locale.time_format == "12h"
    with pytest.raises(SettingsError):
        Settings.from_dict({"locale": {"time_format": "militair"}})


def test_systemclock_kan_tijdzone_runtime_wijzigen():
    from wekker.clock import SystemClock

    klok = SystemClock("UTC")
    assert klok.now().tzname() == "UTC"
    klok.set_timezone("Europe/Amsterdam")
    assert klok.timezone_name == "Europe/Amsterdam"
    assert klok.now().tzinfo is not None
