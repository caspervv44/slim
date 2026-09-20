"""Tests: composition root — veilige defaults, storingsvrije lus, auto-sync."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from wekker.agenda.cache import AgendaCache
from wekker.agenda.providers import ProviderError
from wekker.agenda.sync import AgendaSyncService
from wekker.alarm.state import AlarmState
from wekker.button.controller import ButtonController
from wekker.clock import FakeClock
from wekker.hardware.mock import MockDisplay, MockLamp, MockSpeaker
from wekker.main import build_default, load_settings, maybe_auto_sync, run_once, shutdown
from wekker.settings import default_settings
from wekker.storage import JsonStore


def test_corrupt_bestand_geeft_defaults(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{ongeldig json", encoding="utf-8")
    s = load_settings(JsonStore(p))
    assert s.alarm.time == "07:30"  # veilige defaults, geen crash
    assert p.read_text(encoding="utf-8") == "{ongeldig json"  # niet overschreven


def test_niet_object_json_geeft_defaults(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_settings(JsonStore(p)).alarm.enabled is True


def test_ongeldige_waarden_geeft_defaults(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text('{"alarm": {"time": "99:99"}}', encoding="utf-8")
    assert load_settings(JsonStore(p)).alarm.time == "07:30"


def test_oude_motorsectie_valt_terug_op_defaults(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text('{"physical": {"drive_enabled": true}}', encoding="utf-8")
    s = load_settings(JsonStore(p))
    assert s.lamp.duration_after_button == 30


def test_run_once_vangt_hardwarefout_op(tmp_path):
    rt = build_default(tmp_path / "settings.json")

    class Kapot(MockSpeaker):
        def play(self, sound: str, volume: int) -> None:
            raise RuntimeError("speaker stuk")

    rt.ctx.core._speaker = Kapot()
    rt.ctx.core._settings.alarm.time = rt.ctx.clock.now().strftime("%H:%M")
    # Mag nooit gooien: de lus moet blijven leven bij defecte hardware.
    run_once(rt)
    assert rt.ctx.core.state is AlarmState.SLEEPING
    # Na herstel pikt de volgende tik het alarm alsnog op.
    rt.ctx.core._speaker = MockSpeaker()
    run_once(rt)
    assert rt.ctx.core.state is AlarmState.RINGING


def test_build_default_prototype_hardware(tmp_path):
    rt = build_default(tmp_path / "settings.json")
    assert isinstance(rt.driver, MockDisplay)
    assert isinstance(rt.lamp, MockLamp)
    assert isinstance(rt.controller, ButtonController)
    assert not hasattr(rt, "motor")  # geen motor in eerste prototype
    assert rt.ctx.core.state is AlarmState.SLEEPING


def test_shutdown_zet_lamp_uit(tmp_path):
    rt = build_default(tmp_path / "settings.json")
    rt.controller.lamp_on()
    assert rt.lamp.is_on
    shutdown(rt)
    assert not rt.lamp.is_on


def test_maybe_auto_sync_periodiek(tmp_path):
    rt = build_default(tmp_path / "settings.json")
    assert rt.ctx.cache.status == "never"
    assert maybe_auto_sync(rt) is True  # eerste keer altijd
    assert rt.ctx.cache.status == "ok"
    assert maybe_auto_sync(rt) is False  # binnen interval: overslaan


def test_mislukte_auto_sync_retryt_niet_agressief():
    """Na een mislukte sync geldt last_sync alsnog: geen retry-storm, de UI
    merkt er niets van (sync raakt geen widgets/DOM aan)."""
    from datetime import date

    klok = FakeClock(datetime(2026, 9, 17, 6, 0, tzinfo=timezone.utc))
    pogingen: list = []

    class NetwerkWeg:
        name = "netwerkweg"

        def fetch_day(self, day: date):
            pogingen.append(day)
            raise ProviderError("geen internet")

    cache = AgendaCache()
    rt = SimpleNamespace(ctx=SimpleNamespace(
        settings=default_settings(), cache=cache, clock=klok,
        sync=AgendaSyncService(NetwerkWeg(), cache, klok)))
    # settings default auto_sync_minutes=15.
    assert maybe_auto_sync(rt) is False  # sync faalt eerlijk
    assert len(pogingen) == 1
    klok.advance(timedelta(minutes=5))
    assert maybe_auto_sync(rt) is False  # binnen interval: geen nieuwe poging
    assert len(pogingen) == 1
    assert rt.ctx.cache.status == "error"  # oude (lege) cache + duidelijke status
    klok.advance(timedelta(minutes=10))
    assert maybe_auto_sync(rt) is False
    assert len(pogingen) == 2  # pas na interval opnieuw


def test_maybe_auto_sync_uit_bij_nul(tmp_path):
    rt = build_default(tmp_path / "settings.json")
    rt.ctx.settings = rt.ctx.settings.update_from_dict(
        {"agenda": {"auto_sync_minutes": 0}})
    assert maybe_auto_sync(rt) is False
    assert rt.ctx.cache.status == "never"
