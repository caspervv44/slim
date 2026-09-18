"""Integratie: webinterface — providers, mock-Entree-flow, dashboard."""

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from wekker.agenda.cache import AgendaCache
from wekker.agenda.auth import AuthService, MockEntreeAuth
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


def _req(server, methode, pad, body=None):
    url = f"http://127.0.0.1:{server.server_port}{pad}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=methode,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def _get_html(server, pad):
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{server.server_port}{pad}") as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def test_providers_endpoint(tmp_path):
    ctx = _ctx(tmp_path)
    server = serve_forever(ctx, port=0)
    try:
        code, data = _req(server, "GET", "/api/agenda/providers")
        assert code == 200
        infos = {p["id"]: p for p in data["providers"]}
        assert set(infos) == {"mock", "osiris", "somtoday", "magister", "myx"}
        assert infos["osiris"]["school"] == "ROC Aventus"
        assert infos["osiris"]["auth"] == "entree-oidc"
        assert infos["osiris"]["linked"] is False
        assert infos["mock"]["selected"] is True
        assert infos["somtoday"]["available"] is False
    finally:
        server.shutdown()


def test_auth_status_voor_mock_heeft_geen_login_nodig(tmp_path):
    ctx = _ctx(tmp_path)
    server = serve_forever(ctx, port=0)
    try:
        code, data = _req(server, "GET", "/api/agenda/auth/status")
        assert code == 200
        assert data["provider"] == "mock"
        assert data["linked"] is False
        assert data["login_label"] is None
        code, data = _req(server, "POST", "/api/agenda/auth/start", {})
        assert code == 409
    finally:
        server.shutdown()


def test_volledige_demo_login_flow_via_http(tmp_path):
    ctx = _ctx(tmp_path)
    server = serve_forever(ctx, port=0)
    try:
        # 1. kies Osiris als provider
        code, _ = _req(server, "POST", "/api/settings", {"agenda": {"provider": "osiris"}})
        assert code == 200
        # 2. nog niet gekoppeld
        code, data = _req(server, "GET", "/api/agenda/auth/status")
        assert code == 200 and data["linked"] is False
        assert "Entree" in data["login_label"]
        # 3. items zonder koppeling → 409 met link-hint
        code, data = _req(server, "GET", "/api/agenda/items")
        assert code == 409 and data["action"] == "link"
        # 4. start login → auth_url met state
        code, data = _req(server, "POST", "/api/agenda/auth/start", {})
        assert code == 200 and data["ok"] is True
        state = urllib.parse.parse_qs(
            urllib.parse.urlparse(data["auth_url"]).query)["state"][0]
        # 5. demo-loginpagina vraagt nergens om inloggegevens (geen inputs)
        status, html = _get_html(server, f"/api/agenda/auth/mock?state={state}")
        assert status == 200 and "DEMO" in html
        assert "<input" not in html
        assert 'type="password"' not in html
        # 6. callback rondt af → gekoppeld
        code, data = _req(server, "POST", "/api/agenda/auth/callback", {"state": state})
        assert code == 200 and data["ok"] is True and data["demo"] is True
        code, data = _req(server, "GET", "/api/agenda/auth/status")
        assert data["linked"] is True
        assert data["account"] == "Demo-student (ROC Aventus)"
        # 7. hergebruik van state wordt geweigerd
        code, _ = _req(server, "POST", "/api/agenda/auth/callback", {"state": state})
        assert code == 400
        # 8. agenda-items werken nu, gemarkeerd als demo
        code, data = _req(server, "GET", "/api/agenda/items")
        assert code == 200 and data["provider"] == "osiris"
        assert data["simulated"] is True
        # 9. disconnect verbreekt
        code, data = _req(server, "POST", "/api/agenda/auth/disconnect", {})
        assert code == 200 and data["was_linked"] is True
        code, data = _req(server, "GET", "/api/agenda/auth/status")
        assert data["linked"] is False
    finally:
        server.shutdown()


def test_callback_met_ongeldige_state(tmp_path):
    ctx = _ctx(tmp_path)
    server = serve_forever(ctx, port=0)
    try:
        _req(server, "POST", "/api/settings", {"agenda": {"provider": "osiris"}})
        code, _ = _req(server, "POST", "/api/agenda/auth/callback", {"state": "nep!!"})
        assert code == 400
        code, _ = _req(server, "POST", "/api/agenda/auth/callback", {})
        assert code == 400
        status, _ = _get_html(server, "/api/agenda/auth/mock?state=")
        assert status == 400
    finally:
        server.shutdown()


def test_dashboard_bevat_alle_onderdelen(tmp_path):
    ctx = _ctx(tmp_path)
    server = serve_forever(ctx, port=0)
    try:
        status, html = _get_html(server, "/")
        assert status == 200
        for marker in ("Aventus Wekker", "Status", "Volgende alarm", "Agenda",
                       "Verbinding", "Lamp", "Speaker", "Instellingen"):
            assert marker in html, marker
    finally:
        server.shutdown()


def test_gui_help_zonder_display(tmp_path):
    from wekker.main import main

    with __import__("pytest").raises(SystemExit) as exc:
        main(["gui", "--help"])
    assert exc.value.code == 0
