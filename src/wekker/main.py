"""Composition root: bouwt alle onderdelen en start de wekkerlus.

Eerste prototype: display + speaker + lamp + één button op een Raspberry Pi 5.
Bewegingshardware is uitgesteld naar een latere fase.

Gebruik:
    python -m wekker [--port 8080] [--settings wekker-settings.json]
    python -m wekker simulate [--demo]
    python -m wekker gui [--window]   (touchscreen, fullscreen 800x480)

Op de laptop draait alles met mocks; op de Pi wordt ``build_default``
later uitgebreid met echte drivers zonder de core te wijzigen.
GPIO-pinnen liggen nog nergens vast.
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from wekker.agenda.auth import AuthService, MockEntreeAuth
from wekker.agenda.cache import AgendaCache
from wekker.agenda.myx_auth import MyXAuthManager
from wekker.agenda.providers import build_sync_provider
from wekker.alarm.core import AlarmClock
from wekker.alarm.state import AlarmState
from wekker.api.server import AppContext, serve_forever
from wekker.button.controller import ButtonController
from wekker.clock import SystemClock
from wekker.cloud import CloudSettingsManager, DEFAULT_CLOUD_URL
from wekker.display.manager import DisplayManager
from wekker.display.backlight import BacklightController
from wekker.hardware.interfaces import Button, DisplayDriver, Lamp, Speaker
from wekker.hardware.mock import (
    MockButton,
    MockDisplay,
    MockLamp,
    MockSpeaker,
)
from wekker.logging_config import setup_logging
from wekker.settings import Settings, SettingsError, default_settings
from wekker.storage import JsonStore, StorageError

log = logging.getLogger(__name__)


@dataclass
class Runtime:
    """Alles wat de wekkerlus nodig heeft: context + hardwarehandles.

    Op de laptop zijn dit mocks; op de Pi komen hier de echte drivers met
    dezelfde Protocols (display/speaker/lamp/button).
    """

    ctx: AppContext
    button: Button
    controller: ButtonController
    speaker: Speaker
    lamp: Lamp
    driver: DisplayDriver
    backlight: BacklightController | None = None


def load_settings(store: JsonStore) -> Settings:
    try:
        data = store.load()
    except StorageError as exc:
        # Corrupt of onleesbaar bestand: val terug op veilige defaults zodat
        # de wekker (headless op de Pi) blijft wekken. Het bestand wordt bewust
        # NIET overschreven; herstel via de setup-API (POST schrijft opnieuw).
        log.warning("instellingen onleesbaar, defaults gebruikt: %s", exc)
        return default_settings()
    if data is None:
        return default_settings()
    try:
        return Settings.from_dict(data)
    except SettingsError as exc:
        log.warning("ongeldig instellingenbestand, defaults gebruikt: %s", exc)
        return default_settings()


def build_default(
    settings_path: str | Path = "wekker-settings.json", *, enable_cloud: bool = False
) -> Runtime:
    store = JsonStore(settings_path)
    settings = load_settings(store)
    clock = SystemClock(settings.locale.timezone)
    cloud = None
    if enable_cloud:
        cloud_state_path = Path(settings_path).with_name(".wekker-cloud.json")
        cloud = CloudSettingsManager(
            base_url=os.environ.get("WEKKER_CLOUD_URL", DEFAULT_CLOUD_URL),
            state_path=cloud_state_path,
        )
    speaker, lamp = MockSpeaker(), MockLamp()
    display_driver = MockDisplay()
    button = MockButton()
    cache = AgendaCache()
    display = DisplayManager(display_driver, settings, clock, cache)

    def _wake_on_ring(old: AlarmState, new: AlarmState) -> None:
        if new is AlarmState.RINGING:
            # Alarm gaat af: display aanzetten zodat de status zichtbaar is.
            display.button_pressed()

    core = AlarmClock(settings, clock, speaker, lamp, on_state_change=_wake_on_ring)
    auth = AuthService(clock, providers={"osiris": MockEntreeAuth(clock)})
    myx_auth = MyXAuthManager()
    try:
        sync = build_sync_provider(settings.agenda.provider, cache, clock, auth, myx_auth)
    except Exception as exc:
        # Onbekend platform mag de start nooit blokkeren (zie sync-service).
        log.warning("agenda-provider niet beschikbaar, mock gebruikt: %s", exc)
        sync = build_sync_provider("mock", cache, clock, auth, myx_auth)
    controller = ButtonController(core, lamp, display, clock, settings)
    # Eén fysieke button: eerst de controller (zet o.a. de melding), daarna
    # het display wekken zodat alles in één keer gerenderd wordt.
    button.on_press(controller.press)
    button.on_press(display.button_pressed)
    ctx = AppContext(
        settings, store, clock, core, display, cache, sync, controller, auth,
        myx_auth=myx_auth, cloud=cloud,
    )
    return Runtime(
        ctx=ctx,
        button=button,
        controller=controller,
        speaker=speaker,
        lamp=lamp,
        driver=display_driver,
    )


def _rebuild_sync_provider(rt: Runtime) -> None:
    """Bouw de agenda-provider opnieuw na een provider- of feedwijziging."""
    rt.ctx.sync = build_sync_provider(
        rt.ctx.settings.agenda.provider,
        rt.ctx.cache,
        rt.ctx.clock,
        rt.ctx.auth,
        rt.ctx.myx_auth,
    )


def apply_runtime_settings(rt: Runtime, nieuwe: Settings) -> None:
    """Pas gevalideerde instellingen direct toe op alle runtime-onderdelen."""
    oude_provider = rt.ctx.settings.agenda.provider
    rt.ctx.settings = nieuwe
    rt.ctx.core.update_settings(nieuwe)
    rt.ctx.display.update_settings(nieuwe)
    rt.ctx.button.update_settings(nieuwe)

    set_timezone = getattr(rt.ctx.clock, "set_timezone", None)
    if callable(set_timezone):
        set_timezone(nieuwe.locale.timezone)

    if rt.backlight is not None:
        rt.backlight.set_percent(nieuwe.display.brightness)

    if nieuwe.agenda.provider != oude_provider:
        _rebuild_sync_provider(rt)

    rt.ctx.store.save(nieuwe.to_dict())


def _apply_cloud_feed_update(rt: Runtime, update: dict) -> None:
    """Pas een eenmalige MyX-feedopdracht van het webbeheer toe."""
    cloud = getattr(rt.ctx, "cloud", None)
    auth = getattr(rt.ctx, "myx_auth", None)
    update_id = str(update.get("id", ""))
    action = str(update.get("action", ""))
    if not update_id or auth is None:
        return

    try:
        if action == "set":
            url = str(update.get("url", ""))
            auth.save_feed(url)
            if rt.ctx.settings.agenda.provider != "myx":
                nieuwe = rt.ctx.settings.update_from_dict(
                    {"agenda": {"provider": "myx"}}
                )
                apply_runtime_settings(rt, nieuwe)
            else:
                _rebuild_sync_provider(rt)
        elif action == "clear":
            auth.feed_store.clear()
            _rebuild_sync_provider(rt)
        else:
            return
    except Exception:
        log.exception("MyX-feed uit online beheer kon niet worden toegepast")
        return

    if cloud is not None:
        cloud.acknowledge_feed_update(update_id)
    log.info("MyX-feedopdracht uit online beheer toegepast")


def run_once(rt: Runtime) -> None:
    """Eén wekkertik (1 Hz). Vangt hardwarefouten op zodat één defecte
    driver of één mislukte tick het proces nooit stilzet — de core houdt
    bij een fout zijn oude toestand en probeert het volgende seconde opnieuw.
    """
    try:
        rt.ctx.core.tick()
    except Exception:
        log.exception("alarm-tick faalde; volgende seconde opnieuw geprobeerd")
    try:
        rt.ctx.display.tick()
    except Exception:
        log.exception("display-tick faalde; volgende seconde opnieuw geprobeerd")
    try:
        rt.ctx.button.tick()
    except Exception:
        log.exception("button-tick faalde; volgende seconde opnieuw geprobeerd")
    _update_display_context(rt)
    maybe_auto_sync(rt)
    maybe_cloud_sync(rt)


def _update_display_context(rt: Runtime) -> None:
    """Houd het display bij met alarmtoestand + volgende wektijd."""
    try:
        nxt = rt.ctx.core.next_alarm()
        rt.ctx.display.set_alarm_context(
            rt.ctx.core.state.value,
            nxt.strftime("%H:%M") if nxt else None,
        )
    except Exception:
        log.exception("display-context bijwerken faalde")


def maybe_auto_sync(rt: Runtime) -> bool:
    """Synchroniseer periodiek volgens agenda.auto_sync_minutes (0 = uit).

    Geeft True terug als er gesynchroniseerd is. Fouten markeren de cache
    als error/stale maar stoppen de wekker nooit.
    """
    minutes = rt.ctx.settings.agenda.auto_sync_minutes
    if minutes <= 0:
        return False
    last = rt.ctx.cache.last_sync
    if last is not None:
        from datetime import timedelta

        if rt.ctx.clock.now() - last < timedelta(minutes=minutes):
            return False
    try:
        return rt.ctx.sync.sync_default_window()
    except Exception:
        log.exception("automatische agenda-sync faalde")
        return False



def maybe_cloud_sync(rt: Runtime) -> None:
    """Synchroniseer veilige instellingen met de externe beheerpagina.

    Netwerkverkeer draait in een achtergrondthread. Een ontvangen wijziging
    wordt hier op de hoofdthread gevalideerd en atomair toegepast.
    """
    cloud = getattr(rt.ctx, "cloud", None)
    if cloud is None:
        return

    patch = cloud.consume_remote_patch()
    if patch:
        try:
            nieuwe = rt.ctx.settings.update_from_dict(patch)
            apply_runtime_settings(rt, nieuwe)
            log.info("cloudinstellingen toegepast")
        except Exception:
            log.exception("cloudinstellingen waren ongeldig en zijn genegeerd")

    feed_update = cloud.consume_feed_update()
    if feed_update:
        _apply_cloud_feed_update(rt, feed_update)

    try:
        cloud.maybe_sync(rt.ctx.settings)
    except Exception:
        # Cloudbeheer is optioneel: een storing mag de wekker nooit blokkeren.
        log.exception("cloudsync kon niet worden gestart")


def shutdown(rt: Runtime) -> None:
    """Veilig afsluiten: lamp altijd uit, daarna pas stoppen."""
    try:
        rt.controller.shutdown()
    except Exception:
        log.exception("lamp uitschakelen bij shutdown faalde")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Slimme schoolwekker (mock-modus)")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--settings", default="wekker-settings.json")
    parser.add_argument("--host", default="127.0.0.1")
    sub = parser.add_subparsers(dest="command")
    sim_p = sub.add_parser("simulate", help="lokale simulatie met bestuurbare tijd")
    sim_p.add_argument("--start", default="07:29:50", help="starttijd HH:MM[:SS]")
    sim_p.add_argument("--day", default="2026-09-17", help="simulatiedatum YYYY-MM-DD")
    sim_p.add_argument("--alarm", default="07:30", help="wektijd HH:MM")
    sim_p.add_argument("--snooze", type=int, default=5, help="snoozeminuten")
    sim_p.add_argument("--lampdur", type=int, default=30, help="lampseconden na button")
    sim_p.add_argument("--commands", default=None,
                       help="niet-interactief: ';'-gescheiden commando's")
    sim_p.add_argument("--demo", action="store_true",
                       help="volledige alarmcyclus afspelen en stoppen")
    gui_p = sub.add_parser("gui", help="fullscreen touchscreen-GUI (800x480)")
    gui_p.add_argument("--window", action="store_true",
                       help="venster i.p.v. fullscreen (development op laptop)")
    # Oude opties blijven geaccepteerd zodat bestaande startscripts niet breken.
    # Er wordt geen lokale webserver meer gestart; beheer loopt via veendomain.nl.
    gui_p.add_argument("--host", default=None, help=argparse.SUPPRESS)
    gui_p.add_argument("--port", type=int, default=None, help=argparse.SUPPRESS)
    gui_p.add_argument("--settings", default="wekker-settings.json")
    args = parser.parse_args(argv)
    setup_logging()
    if args.command == "simulate":
        run_simulate(args)
        return
    if args.command == "gui":
        run_gui(args)
        return
    try:
        rt = build_default(args.settings, enable_cloud=True)
    except StorageError as exc:
        log.error("opslagfout: %s", exc)
        raise SystemExit(1) from exc
    server = serve_forever(rt.ctx, host=args.host, port=args.port)
    log.info("wekker gestart (mock-hardware). Stop met Ctrl+C.")
    try:
        while True:
            run_once(rt)
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("stoppen…")
    finally:
        shutdown(rt)
        server.shutdown()


def run_gui(args: argparse.Namespace) -> None:
    """Start de fullscreen touchscreen-GUI zonder lokale webserver.

    Op de Pi: ``python -m wekker gui`` (kiosk: volledig 800x480, geen
    titlebar/panel; Alt+Tab vervalt, Escape sluit af).
    Development: ``python -m wekker gui --window``.
    """
    from wekker.gui.app import launch_gui

    try:
        rt = build_default(args.settings, enable_cloud=True)
    except StorageError as exc:
        log.error("opslagfout: %s", exc)
        raise SystemExit(1) from exc
    rt.backlight = BacklightController()
    rt.backlight.set_percent(rt.ctx.settings.display.brightness)
    log.info(
        "WaveSync gestart met touchscreen-GUI (fullscreen=%s); "
        "online beheer loopt via veendomain.nl.",
        not args.window,
    )
    try:
        launch_gui(rt, fullscreen=not args.window)
    except KeyboardInterrupt:
        log.info("stoppen…")
    finally:
        shutdown(rt)


def run_simulate(args: argparse.Namespace) -> None:
    """Start de simulatie: --demo, --commands of interactieve REPL."""
    from wekker.settings import SettingsError
    from wekker.sim import SimOptions, Simulation, demo_transcript, repl, run_script

    try:
        sim = Simulation(
            SimOptions(
                start=args.start,
                day=args.day,
                alarm=args.alarm,
                snooze_minutes=args.snooze,
                lamp_duration_after_button=args.lampdur,
            )
        )
    except SettingsError as exc:
        print(f"fout: {exc}")
        raise SystemExit(2) from exc
    if args.demo:
        print(demo_transcript(sim))
    elif args.commands:
        raise SystemExit(run_script(sim, args.commands))
    else:
        raise SystemExit(repl(sim))


if __name__ == "__main__":
    main()
