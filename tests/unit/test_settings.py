"""Tests: instellingenvalidatie (eerste prototype: geen motorsectie)."""

import pytest

from wekker.settings import Settings, SettingsError, default_settings


def test_defaults_geldig_en_veilig():
    s = default_settings()
    assert s.alarm.time == "07:30"
    assert s.alarm.snooze_minutes == 9
    assert s.alarm.speaker_enabled is True
    assert s.lamp.duration_after_button == 30
    assert s.lamp.on_with_alarm is True
    assert s.agenda.provider == "mock"
    assert "next_alarm" in s.display.visible_fields
    assert "physical" not in s.to_dict()  # motorsectie verwijderd


def test_ongeldige_wektijd_geweigerd():
    with pytest.raises(SettingsError):
        Settings.from_dict({"alarm": {"time": "25:00"}})
    with pytest.raises(SettingsError):
        Settings.from_dict({"alarm": {"time": "zeven uur"}})


def test_ongeldige_ranges_geweigerd():
    with pytest.raises(SettingsError):
        Settings.from_dict({"alarm": {"volume": 101}})
    with pytest.raises(SettingsError):
        Settings.from_dict({"alarm": {"snooze_minutes": 0}})
    with pytest.raises(SettingsError):
        Settings.from_dict({"display": {"brightness": -1}})
    with pytest.raises(SettingsError):
        Settings.from_dict({"display": {"visible_fields": []}})
    with pytest.raises(SettingsError):
        Settings.from_dict({"display": {"visible_fields": ["tijdmachine"]}})
    with pytest.raises(SettingsError):
        Settings.from_dict({"alarm": {"blink_pattern": "stroboscoop"}})
    with pytest.raises(SettingsError):
        Settings.from_dict({"lamp": {"duration_after_button": 0}})
    with pytest.raises(SettingsError):
        Settings.from_dict({"lamp": {"duration_after_button": 3601}})


def test_onbekende_sleutel_geweigerd():
    s = default_settings()
    with pytest.raises(SettingsError):
        s.update_from_dict({"alarm": {"bestaat_niet": 1}})
    with pytest.raises(SettingsError):
        s.update_from_dict({"onbekende_sectie": {}})
    with pytest.raises(SettingsError):
        Settings.from_dict({"alarm": {}, "allarm": {"time": "08:00"}})
    with pytest.raises(SettingsError):
        Settings.from_dict([1, 2])  # type: ignore[arg-type]
    with pytest.raises(SettingsError):
        Settings.from_dict("tijd")  # type: ignore[arg-type]
    # Oude motorsectie wordt niet meer geaccepteerd (migratie via defaults).
    with pytest.raises(SettingsError):
        Settings.from_dict({"physical": {"drive_enabled": True}})


def test_bools_strikt():
    for veld in ({"enabled": "false"}, {"enabled": 0}, {"enabled": 1},
                 {"lamp_blink": "ja"}, {"speaker_enabled": "true"}):
        with pytest.raises(SettingsError):
            Settings.from_dict({"alarm": veld})
    with pytest.raises(SettingsError):
        Settings.from_dict({"lamp": {"on_with_alarm": 1}})
    s = Settings.from_dict({"alarm": {"enabled": False, "speaker_enabled": False},
                            "lamp": {"on_with_alarm": False}})
    assert s.alarm.enabled is False
    assert s.alarm.speaker_enabled is False
    assert s.lamp.on_with_alarm is False


def test_provider_keuze_beperkt():
    with pytest.raises(SettingsError):
        Settings.from_dict({"agenda": {"provider": "excel"}})
    for naam in ("mock", "magister", "somtoday", "osiris", "myx"):
        assert Settings.from_dict({"agenda": {"provider": naam}}).agenda.provider == naam


def test_gedeeltelijke_update_is_atomair():
    s = default_settings()
    oude_tijd = s.alarm.time
    nieuwe = s.update_from_dict({"alarm": {"time": "08:00"},
                                 "lamp": {"duration_after_button": 45}})
    assert nieuwe.alarm.time == "08:00"
    assert nieuwe.lamp.duration_after_button == 45
    assert s.alarm.time == oude_tijd
    with pytest.raises(SettingsError):
        s.update_from_dict({"alarm": {"time": "99:99"}})
    assert s.alarm.time == oude_tijd


def test_roundtrip_dict():
    s = default_settings()
    assert Settings.from_dict(s.to_dict()).to_dict() == s.to_dict()
