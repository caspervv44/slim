"""Regressietests: ingevulde MyX-cache moet zichtbaar worden in Agenda.

Alle lesdata zijn fictief. Geen netwerk, privélink of Pi nodig.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import importlib.util
from pathlib import Path
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "wakesync_agenda_fix_test", ROOT / "src/wekker/gui/agenda_fix.py"
)
FIX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIX)
TODAY = date(2026, 10, 12)


@dataclass(frozen=True)
class Lesson:
    start: datetime
    end: datetime
    subject: str
    room: str = ""
    teacher: str = ""


@dataclass(frozen=True)
class Main:
    lesson_label: str = "VANDAAG"
    lesson_subject: str = "Geen lessen meer"
    lesson_time: str = ""
    lesson_room: str = ""
    lesson_teacher: str = ""


@dataclass(frozen=True)
class Agenda:
    rows: tuple = ()
    day: str = ""


@dataclass
class Snapshot:
    main: Main
    agenda: Agenda


def les(dag: int, vak: str) -> Lesson:
    return Lesson(
        datetime(2026, 10, dag, 8, 30),
        datetime(2026, 10, dag, 9, 15),
        vak, "B1.02", "Docent",
    )


class Cache:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}
        self.dates = [TODAY + timedelta(days=n) for n in range(33)]

    def get_day(self, day):
        return list(self.mapping.get(day.isoformat(), []))

    def status_dict(self):
        return {"loaded_days": [x.isoformat() for x in self.dates]}


def app_model(cache):
    class App:
        def __init__(self):
            self._runtime = types.SimpleNamespace(ctx=types.SimpleNamespace(
                cache=cache, clock=types.SimpleNamespace(
                    now=lambda: datetime(2026, 10, 12, 23, 15)
                ),
            ))
            self._nav = types.SimpleNamespace(current="main")
            self._agenda_day = TODAY
            self._agenda_page = 1
            self.last = None

        def _data(self):
            gekozen = self._agenda_day or TODAY
            return Snapshot(Main(), Agenda(tuple(cache.get_day(gekozen)), str(gekozen)))

        def render(self):
            self.last = self._data()
            return self.last

        def _go(self, target):
            self._nav.current = target
            return self.render()

        def _shift_agenda_day(self, days):
            self._agenda_day = (self._agenda_day or TODAY) + timedelta(days=days)
            self._agenda_page = 0
            return self.render()

        def _agenda_today(self):
            self._agenda_day = TODAY
            self._agenda_page = 0
            return self.render()

    assert FIX.install_agenda_fix(App)
    return App()


@pytest.fixture()
def cache():
    # Dit bootst precies de gemelde situatie na:
    # 33 gevulde cachedagen, vandaag 0 lessen, later 5 lessen.
    return Cache({
        "2026-10-15": [les(15, "Wiskunde"), les(15, "Nederlands"), les(15, "Engels")],
        "2026-10-19": [les(19, "Biologie"), les(19, "Informatica")],
    })


def test_eerste_opening_agenda_toont_eerste_gevulde_lesdag(cache):
    app = app_model(cache)
    assert not cache.get_day(TODAY)
    data = app._go("agenda")
    assert app._agenda_day == date(2026, 10, 15)
    assert len(data.agenda.rows) == 3
    assert app._agenda_page == 0


def test_pijltjes_bladeren_per_kalenderdag_ook_als_dag_leeg_is(cache):
    app = app_model(cache)
    app._go("agenda")
    assert app._agenda_day == date(2026, 10, 15)

    # Van de lesdag 15 naar 19 oktober geen sprong: elke datum wordt getoond.
    for dag in (16, 17, 18):
        data = app._shift_agenda_day(1)
        assert app._agenda_day == date(2026, 10, dag)
        assert not data.agenda.rows
        assert app._agenda_page == 0

    data = app._shift_agenda_day(1)
    assert app._agenda_day == date(2026, 10, 19)
    assert len(data.agenda.rows) == 2

    for dag in (18, 17, 16, 15):
        data = app._shift_agenda_day(-1)
        assert app._agenda_day == date(2026, 10, dag)
    assert len(data.agenda.rows) == 3


def test_van_19_naar_9_okt_zonder_ontbrekende_dagen():
    # Exact de gemelde situatie: alleen 19 t/m 23 oktober bevatten lessen.
    cache = Cache({
        f"2026-10-{dag:02d}": [les(dag, "Les")]
        for dag in range(19, 24)
    })
    app = app_model(cache)
    app._go("agenda")
    assert app._agenda_day == date(2026, 10, 19)

    for dag in range(18, 8, -1):
        data = app._shift_agenda_day(-1)
        assert app._agenda_day == date(2026, 10, dag)
        assert not data.agenda.rows
        if dag == 12:
            # Een extra render (bijvoorbeeld een kloktick) mag geen
            # automatische sprong naar 19 oktober veroorzaken.
            assert app.render().agenda.day == "2026-10-12"
            assert app._agenda_day == date(2026, 10, 12)


def test_handmatig_bladeren_naar_vandaag_blijft_na_tick_en_tabwissel_staan():
    cache = Cache({"2026-10-19": [les(19, "Wiskunde")]})
    app = app_model(cache)
    app._go("agenda")
    assert app._agenda_day == date(2026, 10, 19)
    for _ in range(7):
        app._shift_agenda_day(-1)
    assert app._agenda_day == TODAY
    assert app.render().agenda.day == "2026-10-12"
    app._go("main")
    app._go("agenda")
    assert app._agenda_day == TODAY


def test_meerdere_dagen_per_actie_volgen_gewoon_timedelta(cache):
    app = app_model(cache)
    app._go("agenda")
    app._shift_agenda_day(7)
    assert app._agenda_day == date(2026, 10, 22)
    app._shift_agenda_day(-14)
    assert app._agenda_day == date(2026, 10, 8)


def test_nu_is_echt_vandaag_en_wordt_niet_automatisch_omgezet(cache):
    app = app_model(cache)
    app._go("agenda")
    assert len(app._agenda_today().agenda.rows) == 0
    assert app._agenda_day == TODAY
    app._go("main")
    app._go("agenda")
    assert app._agenda_day == TODAY


def test_vandaag_toont_ook_eerste_les_van_volgende_dag(cache):
    app = app_model(cache)
    data = app.render()
    assert data.main.lesson_subject == "Wiskunde"
    assert "15 OKT" in data.main.lesson_label
    assert "08:30" in data.main.lesson_time
    assert data.main.lesson_room == "B1.02"


def test_nieuwe_cache_wordt_zichtbaar_zonder_gui_herstart():
    cache = Cache()
    app = app_model(cache)
    data = app._go("agenda")
    assert app._agenda_day == TODAY
    assert not data.agenda.rows
    cache.mapping["2026-10-14"] = [les(14, "Rooster bijwerken")]
    data = app.render()
    assert app._agenda_day == date(2026, 10, 14)
    assert len(data.agenda.rows) == 1


def test_geen_cachelessen_blijft_eerlijk_leeg():
    app = app_model(Cache())
    data = app._go("agenda")
    assert app._agenda_day == TODAY
    assert not data.agenda.rows
    assert data.main.lesson_subject == "Geen lessen meer"


def test_geladen_vandaag_betekent_geen_ongewenste_datumverspringing(cache):
    cache.mapping["2026-10-12"] = [les(12, "Vandaag")]
    app = app_model(cache)
    data = app._go("agenda")
    assert app._agenda_day == TODAY
    assert len(data.agenda.rows) == 1


def test_handmatige_dagselectie_blijft_staan(cache):
    app = app_model(cache)
    app._agenda_day = date(2026, 10, 17)
    data = app._go("agenda")
    assert app._agenda_day == date(2026, 10, 17)
    assert not data.agenda.rows


def test_patch_idempotent(cache):
    app = app_model(cache)
    assert not FIX.install_agenda_fix(app.__class__)


def test_buiten_bereik_geen_oud_rooster(cache):
    assert FIX.zoek_lesdag(cache, date(2027, 1, 1)) is None


def test_niet_toegestane_richting(cache):
    with pytest.raises(ValueError):
        FIX.zoek_lesdag(cache, TODAY, richting=0)


def test_oude_testdummy_geen_crash():
    assert FIX.install_agenda_fix(type("Oud", (), {})) is False


def test_verse_cache_na_handmatig_bezoek_vandaag_forceert_geen_sprong():
    cache = Cache()
    app = app_model(cache)
    app._go("agenda")
    app._shift_agenda_day(1)
    app._shift_agenda_day(-1)
    assert app._agenda_day == TODAY
    cache.mapping["2026-10-19"] = [les(19, "Wiskunde")]
    app.render()
    assert app._agenda_day == TODAY


def test_na_manuele_dagwissel_gaat_geen_privacydata_verloren(cache):
    # De navigatielogica hoort uitsluitend de geselecteerde datum te wijzigen.
    cache_copy = {key: list(value) for key, value in cache.mapping.items()}
    app = app_model(cache)
    app._go("agenda")
    app._shift_agenda_day(-1)
    app._shift_agenda_day(1)
    assert cache.mapping == cache_copy
