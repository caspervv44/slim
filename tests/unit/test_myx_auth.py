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
    MyXFeedStore,
    normalize_feed_url,
)


def _jwt(*, atn_id: int = 123456, seconds: int = 3600, name: str = "Teststudent") -> str:
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
    assert geladen.attendee_id == "123456"
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


def test_feed_url_webcal_wordt_naar_https_genormaliseerd():
    raw = (
        "webcal://aventus.myx.nl/api/InternetCalendar/feed/"
        "11111111-1111-4111-8111-111111111111/"
        "22222222-2222-4222-8222-222222222222"
    )
    assert normalize_feed_url(raw).startswith("https://aventus.myx.nl/")


@pytest.mark.parametrize("url", [
    "https://evil.example/api/InternetCalendar/feed/11111111-1111-4111-8111-111111111111/22222222-2222-4222-8222-222222222222",
    "https://aventus.myx.nl/iets-anders",
    "blob:https://aventus.myx.nl/bd0f404d-e924-41df-b8cc-ba41a088cc6d",
])
def test_feed_url_weigert_onveilige_of_blob_links(url):
    with pytest.raises(MyXAuthError):
        normalize_feed_url(url)


def test_manager_feed_heeft_voorrang_op_tijdelijke_token(tmp_path):
    store = MyXCredentialStore(tmp_path / "myx-auth.json")
    store.save(MyXCredentials.from_token(_jwt(atn_id=777)))
    feed_store = MyXFeedStore(tmp_path / "myx-feed.json")
    feed = (
        "https://aventus.myx.nl/api/InternetCalendar/feed/"
        "11111111-1111-4111-8111-111111111111/"
        "22222222-2222-4222-8222-222222222222"
    )
    feed_store.save(feed)
    manager = MyXAuthManager(
        store=store, feed_store=feed_store, profile_dir=tmp_path / "profile"
    )

    cfg = manager.ensure_config()

    assert cfg.feed_url == feed
    assert manager.status()["connection_mode"] == "feed"
    assert manager.status()["linked"] is True
