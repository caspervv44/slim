"""Integratie: setup-API eerste prototype (echte HTTP tegen testserver)."""

import json
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
from wekker.hardware.mock import MockButton, MockDisplay, MockLamp, MockSpeaker
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


def test_api_settings_beheren(tmp_path):
    ctx = _ctx(tmp_path)
    server = serve_forever(ctx, port=0)
    try:
        code, data = _req(server, "GET", "/api/settings")
        assert code == 200 and data["alarm"]["time"] == "07:30"
        assert "lamp" in data and "physical" not in data
        assert "mock" in data["_providers"]

        code, data = _req(server, "POST", "/api/settings",
                           {"alarm": {"time": "08:15"},
                            "lamp": {"duration_after_button": 45}})
        assert code == 200
        assert data["alarm"]["time"] == "08:15"
        assert data["lamp"]["duration_after_button"] == 45

        code, data = _req(server, "POST", "/api/settings", {"alarm": {"time": "xx"}})
        assert code == 400 and "error" in data

        code, data = _req(server, "POST", "/api/settings", {"alarm": {"onzin": 1}})
        assert code == 400

        # PUT blijft als alias werken.
        code, data = _req(server, "PUT", "/api/settings", {"alarm": {"time": "07:00"}})
        assert code == 200 and data["alarm"]["time"] == "07:00"
    finally:
        server.shutdown()


def test_api_status_en_alarm(tmp_path):
    ctx = _ctx(tmp_path)
    server = serve_forever(ctx, port=0)
    try:
        code, data = _req(server, "GET", "/api/status")
        assert code == 200
        for sleutel in ("state", "now", "next_alarm", "lamp_on",
                        "lamp_timer_active", "speaker_playing", "agenda_stale"):
            assert sleutel in data, sleutel

        # dismiss zonder actief alarm -> 409
        code, data = _req(server, "POST", "/api/alarm/dismiss", {})
        assert code == 409 and data["ok"] is False

        # button indrukken zonder alarm -> lamp aan
        code, data = _req(server, "POST", "/api/button/press", {})
        assert code == 200 and data["result"] == "lamp-aan"
        code, data = _req(server, "GET", "/api/status")
        assert data["lamp_on"] is True and data["lamp_timer_active"] is True
    finally:
        server.shutdown()


def test_api_lamp_en_speaker(tmp_path):
    ctx = _ctx(tmp_path)
    server = serve_forever(ctx, port=0)
    try:
        code, data = _req(server, "POST", "/api/lamp/on", {"duration_seconds": 60})
        assert code == 200 and "60s" in data["result"]
        code, data = _req(server, "POST", "/api/lamp/off", {})
        assert code == 200
        code, data = _req(server, "GET", "/api/status")
        assert data["lamp_on"] is False

        code, data = _req(server, "POST", "/api/lamp/on", {"duration_seconds": 0})
        assert code == 400

        code, data = _req(server, "POST", "/api/lamp/test", {})
        assert code == 200

        code, data = _req(server, "POST", "/api/speaker/test", {})
        assert code == 200 and data["sound"] == "beep"
        code, data = _req(server, "GET", "/api/status")
        assert data["speaker_playing"] is False  # na test weer gestopt
    finally:
        server.shutdown()


def test_api_agenda(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.clock.set(datetime(2026, 9, 14, 7, 0, tzinfo=timezone.utc))
    server = serve_forever(ctx, port=0)
    try:
        code, data = _req(server, "GET", "/api/agenda/status")
        assert code == 200 and data["status"] == "never"
        assert data["stale"] is True
        assert "mock" in data["available_providers"]
        assert data["connected"] is True

        # items vóór sync: leeg maar geldig, gemarkeerd gesimuleerd
        code, data = _req(server, "GET", "/api/agenda/items")
        assert code == 200 and data["simulated"] is True and data["items"] == []

        assert ctx.sync.sync_today() is True
        code, data = _req(server, "GET", "/api/agenda/items")
        assert code == 200 and len(data["items"]) == 4
        assert data["items"][0]["subject"] == "Wiskunde"
        assert data["items"][0]["simulated"] is True

        # ander platform: eerlijke 501
        code, _ = _req(server, "POST", "/api/settings", {"agenda": {"provider": "magister"}})
        assert code == 200
        code, data = _req(server, "GET", "/api/agenda/items")
        assert code == 501 and "nog niet beschikbaar" in data["error"]
        code, data = _req(server, "GET", "/api/agenda/status")
        assert data["connected"] is False

        code, data = _req(server, "GET", "/api/lexisteert-niet")
        assert code == 404
    finally:
        server.shutdown()


def test_api_wijst_ongeldige_body_af(tmp_path):
    import http.client

    ctx = _ctx(tmp_path)
    server = serve_forever(ctx, port=0)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        conn.request("POST", "/api/settings", body="{geen json",
                     headers={"Content-Type": "application/json"})
        assert conn.getresponse().status == 400
        conn.close()
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        conn.request("POST", "/api/settings", body="x" * (64 * 1024 + 1),
                     headers={"Content-Type": "application/json"})
        assert conn.getresponse().status == 413
        conn.close()
    finally:
        server.shutdown()
