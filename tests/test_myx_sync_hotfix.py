"""Regressietests voor de lokale MyX-sync-hotfix (zonder netwerk of privé-URL).

Deze tests draaien met de echte WakeSync-modules plus testdoubles; de
Raspberry Pi en een daadwerkelijk bereikbare MyX-feed blijven apart te testen.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def tool():
    path = Path(__file__).resolve().parents[1] / "tools" / "configure_private_myx.py"
    spec = importlib.util.spec_from_file_location("wakesync_myx_hotfix_tool", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _settings(path, provider="mock", auto_sync=0):
    # Alleen de benodigde velden; het project vult overige velden met defaults.
    from wekker.storage import JsonStore
    JsonStore(path).save({
        "agenda": {"provider": provider, "auto_sync_minutes": auto_sync},
    })


def test_urls_en_tokens_worden_nooit_geprint(tool):
    error = "GET https://aventus.myx.nl/api/InternetCalendar/feed/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/secret error, Bearer abc123"
    redacted = tool._public_error(error)
    assert "https://" not in redacted
    assert "aaaaaaaa-aaaa" not in redacted
    assert "abc123" not in redacted


def test_geen_nieuwe_config_aanmaken_bij_verkeerd_pad(tool, tmp_path):
    with pytest.raises(tool.StorageError):
        tool._ensure_provider(tmp_path / "bestaat-niet.json")
    assert not (tmp_path / "bestaat-niet.json").exists()


def test_provider_en_syncworden_gezet_zonder_alarminstellingen_te_wissen(tool, tmp_path):
    from wekker.settings import Settings
    from wekker.storage import JsonStore

    path = tmp_path / "wekker-settings.json"
    original = Settings.from_dict({
        "agenda": {"provider": "mock", "auto_sync_minutes": 0},
        "alarm": {"time": "06:45", "volume": 40},
    })
    JsonStore(path).save(original.to_dict())
    changed = tool._ensure_provider(path)
    after = Settings.from_dict(JsonStore(path).load())
    assert changed
    assert after.agenda.provider == "myx"
    assert after.agenda.auto_sync_minutes == 15
    assert after.alarm.time == "06:45"
    assert after.alarm.volume == 40
    assert not tool._ensure_provider(path)


def test_refresh_vult_echte_cache_route_zonder_secret_te_tonen(
    tool, monkeypatch, tmp_path, capsys
):
    path = tmp_path / "wekker-settings.json"
    _settings(path, "myx", 15)
    monkeypatch.setattr(tool, "_load_secret", lambda: True)
    when = __import__("datetime").datetime(2026, 10, 12)
    data = SimpleNamespace(
        status_dict=lambda: {
            "loaded_days": ["2026-10-12", "2026-10-13"],
            "status": "ok",
            "error": None,
        },
        get_day=lambda day: ["les"] if day.isoformat() == "2026-10-13" else [],
    )
    sync = SimpleNamespace(
        sync_default_window=lambda: True,
        _provider=SimpleNamespace(sync_horizon_days=21),
    )
    ctx = SimpleNamespace(
        settings=SimpleNamespace(agenda=SimpleNamespace(provider="myx")),
        myx_auth=SimpleNamespace(status=lambda: {"feed_configured": True}),
        clock=SimpleNamespace(now=lambda: when),
        sync=sync,
        cache=data,
    )
    fake_runtime = SimpleNamespace(ctx=ctx)
    import wekker.main as main
    monkeypatch.setattr(main, "build_default", lambda _p, enable_cloud: fake_runtime)
    called = []
    monkeypatch.setattr(main, "shutdown", lambda _rt: called.append(True))

    rc = tool.configure(path, refresh=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Synchronisatie: GELUKT" in out
    assert "Lessen komende 21 dagen: 1" in out
    assert called == [True]


def test_mislukte_sync_toont_eerlijke_fout_en_geen_url(
    tool, monkeypatch, tmp_path, capsys
):
    path = tmp_path / "wekker-settings.json"
    _settings(path, "myx", 15)
    monkeypatch.setattr(tool, "_load_secret", lambda: True)
    data = SimpleNamespace(status_dict=lambda: {
        "status": "error",
        "error": "HTTP https://aventus.myx.nl/api/InternetCalendar/feed/abc mislukt",
    })
    ctx = SimpleNamespace(
        settings=SimpleNamespace(agenda=SimpleNamespace(provider="myx")),
        myx_auth=SimpleNamespace(status=lambda: {"feed_configured": True}),
        sync=SimpleNamespace(sync_default_window=lambda: False),
        cache=data,
    )
    import wekker.main as main
    monkeypatch.setattr(main, "build_default", lambda _p, enable_cloud: SimpleNamespace(ctx=ctx))
    monkeypatch.setattr(main, "shutdown", lambda _rt: None)

    assert tool.configure(path, refresh=True) == 1
    output = capsys.readouterr().err
    assert "Synchronisatie mislukt" in output
    assert "https://" not in output
    assert "abc" not in output


def test_geen_geheim_betekent_eerlijke_fout_zonder_wijziging(
    tool, monkeypatch, tmp_path, capsys
):
    path = tmp_path / "wekker-settings.json"
    _settings(path, "mock", 15)
    monkeypatch.setattr(tool, "_load_secret", lambda: False)
    before = path.read_bytes()
    assert tool.configure(path, refresh=True) == 2
    assert path.read_bytes() == before
    assert "geen bruikbare myx-feed" in capsys.readouterr().err.lower()
