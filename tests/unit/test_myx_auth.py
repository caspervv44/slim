"""Tests voor persistente MyX-browserauthenticatie zonder echte browser."""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from wekker.agenda.myx_auth import (
    MyXAuthError,
    MyXAuthManager,
    MyXCredentialStore,
    MyXCredentials,
)


def _jwt(*, atn_id: int = 195711, seconds: int = 3600, name: str = "Teststudent") -> str:
    now = datetime.now(timezone.utc)

    def enc(obj):
        raw = json.dumps(obj, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    header = enc({"alg": "none", "typ": "JWT"})
    payload = enc({
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=seconds)).timestamp()),
        "atnId": atn_id,
        "name": name,
    })
    # Handtekening is voor deze unit-test niet relevant: productie verkrijgt
    # het token via HTTPS/MyX en leest hier alleen exp/atnId uit.
    return f"{header}.{payload}.test"


def test_credentials_leest_expiry_en_attendee_id():
    creds = MyXCredentials.from_token(_jwt(atn_id=12345))
    assert creds.attendee_id == "12345"
    assert creds.valid_for(60)
    assert creds.account_label == "Teststudent"


@pytest.mark.parametrize("token", ["", "geen-jwt", "a.b.c"])
def test_ongeldig_token_wordt_geweigerd(token):
    with pytest.raises(MyXAuthError):
        MyXCredentials.from_token(token)


def test_store_roundtrip_en_bestandsrechten(tmp_path):
    path = tmp_path / "auth" / "myx-auth.json"
    store = MyXCredentialStore(path)
    creds = MyXCredentials.from_token(_jwt())
    store.save(creds)

    geladen = store.load()
    assert geladen is not None
    assert geladen.attendee_id == "195711"
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


def test_manager_gebruikt_opgeslagen_token_in_config(tmp_path):
    store = MyXCredentialStore(tmp_path / "myx-auth.json")
    store.save(MyXCredentials.from_token(_jwt(atn_id=777)))
    manager = MyXAuthManager(store=store, profile_dir=tmp_path / "profile")

    cfg = manager.ensure_config()

    assert cfg.configured
    assert cfg.att_id == "777"
    assert manager.status()["token_valid"] is True


def test_disconnect_verwijdert_token_en_browserprofiel(tmp_path):
    store = MyXCredentialStore(tmp_path / "myx-auth.json")
    store.save(MyXCredentials.from_token(_jwt()))
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "Cookies").write_text("dummy")
    manager = MyXAuthManager(store=store, profile_dir=profile)

    assert manager.disconnect() is True
    assert not store.path.exists()
    assert not profile.exists()
    assert manager.status()["linked"] is False


def test_verlopen_token_zonder_profiel_vraagt_login(tmp_path, monkeypatch):
    store = MyXCredentialStore(tmp_path / "myx-auth.json")
    store.save(MyXCredentials.from_token(_jwt(seconds=-60)))
    manager = MyXAuthManager(store=store, profile_dir=tmp_path / "geen-profiel")
    monkeypatch.delenv("WEKKER_MYX_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("WEKKER_MYX_ATT_ID", raising=False)

    with pytest.raises(MyXAuthError, match="gekoppeld|inloggen"):
        manager.ensure_config()


def test_start_interactive_is_eenmalig_tijdens_lopende_worker(tmp_path, monkeypatch):
    manager = MyXAuthManager(
        store=MyXCredentialStore(tmp_path / "auth.json"),
        profile_dir=tmp_path / "profile",
    )
    started = []

    blocker = __import__("threading").Event()

    def fake_login():
        started.append(True)
        blocker.wait(timeout=1)

    monkeypatch.setattr(manager, "login_interactive", fake_login)
    assert manager.start_interactive() is True
    # Wacht kort tot de thread daadwerkelijk draait.
    for _ in range(50):
        if started:
            break
        __import__("time").sleep(0.01)
    assert manager.start_interactive() is False
    blocker.set()
