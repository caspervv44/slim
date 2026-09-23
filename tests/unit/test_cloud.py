from __future__ import annotations

from pathlib import Path

from wekker.cloud import CloudSettingsManager, cloud_settings
from wekker.settings import default_settings


def test_cloud_settings_never_contains_agenda_or_secrets() -> None:
    data = cloud_settings(default_settings())
    assert set(data) == {"alarm", "lamp", "display", "locale"}
    assert "agenda" not in data


def test_registration_state_is_stored_and_displayed(tmp_path: Path, monkeypatch) -> None:
    manager = CloudSettingsManager("https://example.test/test2.pl", tmp_path / "cloud.json")
    before = manager.display_info()

    assert before.ready is True
    assert before.username == "basis"
    assert len(before.initial_password) == 16
    assert "test2.pl?d=" in before.management_url

    def fake(action, payload, *, state=None):
        assert action == "register"
        assert payload["device_id"] in before.management_url
        assert payload["initial_password"] == before.initial_password
        return {
            "ok": True,
            "management_url": before.management_url,
            "username": "basis",
            "revision": 1,
        }

    monkeypatch.setattr(manager, "_json_request", fake)
    manager.sync_now_for_test(default_settings())

    info = manager.display_info()
    assert info.ready is True
    assert info.username == "basis"
    assert info.initial_password == before.initial_password
    assert "test2.pl?d=" in info.management_url
    assert manager._load_state()["registered"] is True


def test_new_remote_revision_becomes_pending_patch(tmp_path: Path, monkeypatch) -> None:
    manager = CloudSettingsManager("https://example.test/test2.pl", tmp_path / "cloud.json")
    local = cloud_settings(default_settings())
    manager._save_state({
        "device_id": "a" * 64,
        "device_key": "b" * 64,
        "management_url": "https://example.test/test2.pl?d=" + "a" * 64,
        "username": "basis",
        "initial_password": "AbCdEfGh23456789",
        "password_changed": False,
        "revision": 1,
        "last_synced_hash": "irrelevant",
    })

    remote = cloud_settings(default_settings())
    remote["locale"]["time_format"] = "12h"

    def fake(action, payload, *, state=None):
        assert action == "pull"
        return {
            "ok": True,
            "settings": remote,
            "revision": 2,
            "password_changed": True,
        }

    monkeypatch.setattr(manager, "_json_request", fake)
    manager.sync_now_for_test(default_settings())

    assert manager.consume_remote_patch()["locale"]["time_format"] == "12h"
    assert manager.display_info().password_changed is True
