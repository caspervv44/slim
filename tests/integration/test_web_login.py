"""Integratie: prototype-weblogin (casper/casper) voor de setup-API.

- Zonder sessie: /api/* → 401, PUT /api/settings → 401.
- Verkeerde credentials → 401 met generieke melding; wachtwoord lekt nergens
  (niet in response, niet in logs).
- Juiste credentials → sessiecookie (HttpOnly); daarna werkt de API.
- Logout trekt de sessie in; oude cookie wordt geweigerd.
"""

import json
import logging
import urllib.request
from datetime import datetime, timezone

from wekker.agenda.auth import AuthService, MockEntreeAuth
from wekker.agenda.cache import AgendaCache
from wekker.agenda.providers import MockAgendaProvider
from wekker.agenda.sync import AgendaSyncService
from wekker.alarm.core import AlarmClock
from wekker.api.server import AppContext, serve_forever
from wekker.button.controller import ButtonController
from wekker.clock import FakeClock
from wekker.display.manager import DisplayManager
from wekker.hardware.mock import MockDisplay, MockLamp, MockSpeaker
from wekker.settings import default_settings
from wekker.storage import JsonStore


def _ctx(tmp_path):
    s = default_settings()
    klok = FakeClock(datetime(2026, 9, 17, 6, 0, tzinfo=timezone.utc))
    speaker, lamp = MockSpeaker(), MockLamp()
    driver = MockDisplay()
    core = AlarmClock(s, klok, speaker, lamp)
    cache = AgendaCache()
    display = DisplayManager(driver, s, klok, cache)
    sync = AgendaSyncService(MockAgendaProvider(), cache, klok)
    button = ButtonController(core, lamp, display, klok, s)
    auth = AuthService(klok, providers={"osiris": MockEntreeAuth(klok)})
    return AppContext(s, JsonStore(tmp_path / "s.json"), klok, core, display,
                      cache, sync, button, auth)


def _raw(server, methode, pad, body=None, cookie=None):
    url = f"http://127.0.0.1:{server.server_port}{pad}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, data=data, method=methode, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode(), resp.headers
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(), exc.headers


def _login(server):
    code, _, headers = _raw(server, "POST", "/api/login",
                             {"username": "casper", "password": "casper"})
    assert code == 200
    set_cookie = headers.get("Set-Cookie", "")
    assert "HttpOnly" in set_cookie
    return set_cookie.split(";")[0]


def test_api_vereist_login(tmp_path):
    ctx = _ctx(tmp_path)
    server = serve_forever(ctx, port=0)
    try:
        for methode, pad, body in (
            ("GET", "/api/status", None),
            ("GET", "/api/settings", None),
            ("POST", "/api/settings", {"alarm": {"time": "08:00"}}),
            ("PUT", "/api/settings", {"alarm": {"time": "08:00"}}),
            ("POST", "/api/lamp/on", {}),
            ("GET", "/api/agenda/providers", None),
        ):
            code, body_tekst, _ = _raw(server, methode, pad, body)
            assert code == 401, (methode, pad)
            assert "Inloggen vereist" in body_tekst
    finally:
        server.shutdown()


def test_login_met_verkeerde_credentials(tmp_path, caplog):
    ctx = _ctx(tmp_path)
    server = serve_forever(ctx, port=0)
    geheim = "fout-wachtwoord-xyz-123"
    try:
        with caplog.at_level(logging.INFO, logger="wekker.api.webauth"):
            code, body_tekst, headers = _raw(
                server, "POST", "/api/login",
                {"username": "casper", "password": geheim})
        assert code == 401
        assert "Onjuiste inloggegevens" in body_tekst
        # Wachtwoord lekt nergens heen.
        assert geheim not in body_tekst
        assert geheim not in caplog.text
        assert headers.get("Set-Cookie") is None
        # Foutieve gebruikersnaam geeft dezelfde generieke melding.
        code, body_tekst, _ = _raw(server, "POST", "/api/login",
                                   {"username": "onbekend", "password": "casper"})
        assert code == 401 and "Onjuiste inloggegevens" in body_tekst
        # Ontbrekende velden ook.
        code, _, _ = _raw(server, "POST", "/api/login", {})
        assert code == 401
    finally:
        server.shutdown()


def test_login_logout_rondje(tmp_path):
    ctx = _ctx(tmp_path)
    server = serve_forever(ctx, port=0)
    try:
        cookie = _login(server)
        code, body_tekst, _ = _raw(server, "GET", "/api/status", cookie=cookie)
        assert code == 200
        assert '"timezone": "Europe/Amsterdam"' in body_tekst
        # Uitloggen trekt de sessie in en wist de cookie.
        code, _, headers = _raw(server, "POST", "/api/logout", {}, cookie=cookie)
        assert code == 200
        assert "Max-Age=0" in (headers.get("Set-Cookie") or "")
        # Oude cookie wordt nu geweigerd.
        code, _, _ = _raw(server, "GET", "/api/status", cookie=cookie)
        assert code == 401
    finally:
        server.shutdown()


def test_gerommeld_cookie_wordt_geweigerd(tmp_path):
    ctx = _ctx(tmp_path)
    server = serve_forever(ctx, port=0)
    try:
        code, _, _ = _raw(server, "GET", "/api/status",
                           cookie="wekker_session=geen-echt-token")
        assert code == 401
    finally:
        server.shutdown()
