"""Tests: OSIRIS-configuratie via environment (alleen namen in code/docs).

Er bestaat geen echte OSIRIS-configuratie; deze tests bewijzen dat ontbreken
eerlijk wordt gemeld en dat waarden nergens lekken. Geen internet, geen
schoolaccount, geen secrets in tests (gebruikte waarden zijn nep-markers).
"""

from datetime import date, datetime, timezone

from wekker.agenda.auth import AuthService, MockEntreeAuth
from wekker.agenda.osiris import (
    ENV_OSIRIS_BASE_URL,
    ENV_OSIRIS_CLIENT_ID,
    ENV_OSIRIS_REDIRECT_URI,
    REQUIRED_OSIRIS_ENV,
    OsirisAgendaProvider,
    OsirisConfig,
)
from wekker.clock import FakeClock


def _klok():
    return FakeClock(datetime(2026, 9, 17, 6, 0, tzinfo=timezone.utc))


def _auth(klok):
    return AuthService(klok, providers={"osiris": MockEntreeAuth(klok)})


def test_vereiste_env_namen_liggen_vast():
    assert REQUIRED_OSIRIS_ENV == (
        "WEKKER_OSIRIS_BASE_URL",
        "WEKKER_OSIRIS_CLIENT_ID",
        "WEKKER_OSIRIS_REDIRECT_URI",
    )
    assert {ENV_OSIRIS_BASE_URL, ENV_OSIRIS_CLIENT_ID, ENV_OSIRIS_REDIRECT_URI} == set(
        REQUIRED_OSIRIS_ENV
    )


def test_zonder_env_niet_geconfigureerd(monkeypatch):
    for naam in REQUIRED_OSIRIS_ENV:
        monkeypatch.delenv(naam, raising=False)
    cfg = OsirisConfig.from_env()
    assert cfg.configured is False
    assert cfg.missing() == list(REQUIRED_OSIRIS_ENV)


def test_met_env_geconfigureerd(monkeypatch):
    monkeypatch.setenv(ENV_OSIRIS_BASE_URL, "https://voorbeeld.invalid/osiris")
    monkeypatch.setenv(ENV_OSIRIS_CLIENT_ID, "voorbeeld-client")
    monkeypatch.setenv(ENV_OSIRIS_REDIRECT_URI, "http://wekker:8080/callback")
    cfg = OsirisConfig.from_env()
    assert cfg.configured is True
    assert cfg.missing() == []


def test_deels_geconfigureerd_noemt_alleen_namen(monkeypatch):
    geheim = "super-geheime-waarde-xyz"
    monkeypatch.setenv(ENV_OSIRIS_BASE_URL, geheim)
    monkeypatch.delenv(ENV_OSIRIS_CLIENT_ID, raising=False)
    monkeypatch.delenv(ENV_OSIRIS_REDIRECT_URI, raising=False)
    cfg = OsirisConfig.from_env()
    assert cfg.configured is False
    assert geheim not in cfg.missing()
    assert geheim not in str(cfg.missing())
    assert cfg.missing() == [ENV_OSIRIS_CLIENT_ID, ENV_OSIRIS_REDIRECT_URI]


def test_provider_zonder_config_gebruikt_env_en_blijft_demo(monkeypatch):
    for naam in REQUIRED_OSIRIS_ENV:
        monkeypatch.delenv(naam, raising=False)
    klok = _klok()
    auth = _auth(klok)
    provider = OsirisAgendaProvider(auth)
    assert provider.config.configured is False
    # Gekoppeld zonder echte config: nog steeds expliciet gelabelde demodata
    # (geen regressie van de werkende demo-flow), nooit als echt gepresenteerd.
    flow = auth.start_flow("osiris", "http://x")
    auth.complete_flow("osiris", flow.state)
    lessen = provider.fetch_day(date(2026, 9, 17))
    assert lessen and all(les.source == "osiris-demo" for les in lessen)


def test_expliciete_config_op_provider():
    klok = _klok()
    cfg = OsirisConfig(base_url="https://voorbeeld.invalid", client_id="c",
                       redirect_uri="http://x", _present=REQUIRED_OSIRIS_ENV)
    provider = OsirisAgendaProvider(_auth(klok), config=cfg)
    assert provider.config.configured is True
