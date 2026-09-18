"""Tests: authenticatie-abstractie (demo-flow, nooit wachtwoorden)."""

from datetime import datetime, timedelta, timezone

import pytest

from wekker.agenda.auth import (
    AuthError,
    AuthService,
    MockEntreeAuth,
)
from wekker.clock import FakeClock


def _klok():
    return FakeClock(datetime(2026, 9, 14, 7, 0, tzinfo=timezone.utc))


def _auth():
    klok = _klok()
    return AuthService(klok, providers={"osiris": MockEntreeAuth(klok)}), klok


def test_start_geeft_url_en_state():
    auth, _ = _auth()
    flow = auth.start_flow("osiris", "http://wekker:8080")
    assert flow.state
    assert len(flow.state) <= 128
    assert flow.auth_url.startswith("http://wekker:8080/api/agenda/auth/mock?state=")
    assert flow.expires_at > auth.clock.now()


def test_complete_koppelt_demo_account_zonder_geheimen():
    auth, _ = _auth()
    assert auth.is_linked("osiris") is False
    flow = auth.start_flow("osiris", "http://x")
    link = auth.complete_flow("osiris", flow.state)
    assert link.provider_id == "osiris"
    assert link.demo is True
    assert "wachtwoord" not in link.to_dict()
    assert "token" not in " ".join(link.to_dict())
    assert "password" not in " ".join(link.to_dict())
    assert auth.is_linked("osiris") is True
    assert auth.get_link("osiris").account_label == link.account_label


def test_state_is_eenmalig():
    auth, _ = _auth()
    flow = auth.start_flow("osiris", "http://x")
    auth.complete_flow("osiris", flow.state)
    with pytest.raises(AuthError):
        auth.complete_flow("osiris", flow.state)


def test_onbekende_state_wordt_geweigerd():
    auth, _ = _auth()
    with pytest.raises(AuthError):
        auth.complete_flow("osiris", "nooit-uitgegeven-state")


def test_verlopen_state_wordt_geweigerd():
    auth, klok = _auth()
    flow = auth.start_flow("osiris", "http://x")
    klok.advance(timedelta(minutes=11))
    with pytest.raises(AuthError) as exc:
        auth.complete_flow("osiris", flow.state)
    assert "verlopen" in str(exc.value)


def test_disconnect_verbreekt_koppeling():
    auth, _ = _auth()
    assert auth.disconnect("osiris") is False
    flow = auth.start_flow("osiris", "http://x")
    auth.complete_flow("osiris", flow.state)
    assert auth.disconnect("osiris") is True
    assert auth.is_linked("osiris") is False


def test_onbekende_provider_geeft_fout():
    auth, _ = _auth()
    with pytest.raises(AuthError):
        auth.start_flow("magister", "http://x")
    with pytest.raises(AuthError):
        auth.complete_flow("magister", "state")
