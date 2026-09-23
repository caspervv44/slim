"""Tests: provider-register en Osiris-voorbereiding (geen school-ifs in core)."""

import pytest

from wekker.agenda.auth import AuthService, MockEntreeAuth
from wekker.agenda.osiris import OSIRIS_DEMO_SOURCE, OsirisAgendaProvider
from wekker.agenda.providers import (
    ProviderError,
    create_provider,
    get_provider_info,
    list_providers,
)
from wekker.clock import FakeClock
from datetime import date, datetime, timezone


def _klok():
    return FakeClock(datetime(2026, 9, 14, 7, 0, tzinfo=timezone.utc))


def _auth():
    klok = _klok()
    return AuthService(klok, providers={"osiris": MockEntreeAuth(klok)})


def test_register_bevat_alle_platformen():
    infos = {i.id: i for i in list_providers()}
    assert set(infos) == {"mock", "osiris", "somtoday", "magister", "myx"}
    assert infos["mock"].available is True
    assert infos["mock"].auth == "none"
    assert infos["osiris"].school == "ROC Aventus"
    assert infos["osiris"].auth == "entree-oidc"
    assert infos["osiris"].available is True
    for later in ("somtoday", "magister"):
        assert infos[later].available is False
    assert infos["myx"].available is True
    assert infos["myx"].auth == "browser-sso"
    with pytest.raises(ValueError):
        get_provider_info("hogwarts")


def test_mock_blijft_werken():
    provider = create_provider("mock")
    lessen = provider.fetch_day(date(2026, 9, 14))
    assert len(lessen) == 4
    assert all(les.source == "mock" for les in lessen)


def test_onbeschikbare_providers_geven_duidelijke_fout():
    for naam in ("somtoday", "magister"):
        with pytest.raises(ProviderError) as exc:
            create_provider(naam)
        assert "nog niet beschikbaar" in str(exc.value)


def test_osiris_zonder_koppeling_verwijst_naar_webinterface():
    provider = OsirisAgendaProvider(_auth())
    assert provider.name == "osiris"
    with pytest.raises(ProviderError) as exc:
        provider.fetch_day(date(2026, 9, 14))
    assert "niet gekoppeld" in str(exc.value)


def test_osiris_met_demo_koppeling_geeft_gemarkeerde_data():
    auth = _auth()
    flow = auth.start_flow("osiris", "http://localhost:8080")
    auth.complete_flow("osiris", flow.state)
    provider = OsirisAgendaProvider(auth)
    lessen = provider.fetch_day(date(2026, 9, 14))
    assert len(lessen) == 4
    assert all(les.source == OSIRIS_DEMO_SOURCE for les in lessen)
    assert all(les.to_dict()["simulated"] is True for les in lessen)


def test_osiris_zonder_auth_store_weigert():
    with pytest.raises(ProviderError):
        create_provider("osiris", None)
