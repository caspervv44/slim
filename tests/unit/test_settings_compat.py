"""Tests: settings backwards compatibility en robuuste input.

Oude instellingenbestanden (van vóór de locale-sectie) moeten blijven laden;
ongeldige input wordt overal geweigerd zonder bestaande config te breken.
"""

import pytest

from wekker.settings import Settings, SettingsError, default_settings


def test_oud_bestand_zonder_locale_krijgt_defaults():
    oud = {
        "alarm": {"time": "06:45"},
        "lamp": {"duration_after_button": 20},
        "display": {"brightness": 60},
        "agenda": {"provider": "mock"},
    }
    s = Settings.from_dict(oud)
    assert s.alarm.time == "06:45"
    assert s.locale.timezone == "Europe/Amsterdam"
    assert s.locale.region == "NL"


def test_leeg_bestand_geeft_defaults():
    assert Settings.from_dict({}) == default_settings()


def test_locale_update_via_api_vorm():
    s = default_settings()
    nieuwe = s.update_from_dict({"locale": {"timezone": "Europe/Amsterdam"}})
    assert nieuwe.locale.timezone == "Europe/Amsterdam"
    with pytest.raises(SettingsError):
        s.update_from_dict({"locale": {"timezone": "UTC+1", "region": "XX"}})
    # Oude object ongewijzigd na geweigerde update.
    assert s.locale.timezone == "Europe/Amsterdam"


def test_locale_onbekende_sleutel_geweigerd():
    with pytest.raises(SettingsError):
        Settings.from_dict({"locale": {"tijdzone": "Europe/Amsterdam"}})


@pytest.mark.parametrize("patch", [
    {"alarm": {"time": "07:30:00"}},  # strikt HH:MM, geen seconden
    {"alarm": {"volume": "hard"}},
    {"alarm": {"enabled": 1}},
    {"lamp": {"duration_after_button": -5}},
    {"display": {"brightness": 101}},
    {"display": {"night_mode": "aan"}},
    {"agenda": {"auto_sync_minutes": -1}},
    {"agenda": {"provider": "MOCK"}},  # hoofdlettergevoelig
    {"locale": {"timezone": "europe/amsterdam"}},  # IANA is hoofdlettergevoelig
    {"locale": {"region": "nl-EXTRA"}},
    {"locale": {"timezone": None}},
])
def test_ongeldige_waarden_geweigerd(patch):
    with pytest.raises(SettingsError):
        default_settings().update_from_dict(patch)


def test_none_en_verkeerde_types_geweigerd():
    with pytest.raises(SettingsError):
        Settings.from_dict(None)  # type: ignore[arg-type]
    with pytest.raises(SettingsError):
        Settings.from_dict({"alarm": None})  # type: ignore[dict-item]
