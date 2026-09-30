"""WakeSync composition root en 1-Hz alarmlus.

De hoofdthread doet alleen snelle, lokale handelingen: alarmtick, displaymodel,
touch/UI en het verwerken van resultaten uit achtergrondtaken. Agenda-HTTP,
feedopslag en cloud-HTTP blokkeren de alarmtijdlijn niet.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
import sys

from wekker.agenda.auth import AuthService, MockEntreeAuth
from wekker.agenda.cache import AgendaCache
from wekker.agenda.myx_auth import MyXAuthManager
from wekker.agenda.providers import build_sync_provider
from wekker.alarm.core import AlarmClock
from wekker.alarm.persistence import AlarmRuntimeStore
from wekker.alarm.state import AlarmState
from wekker.api.server import AppContext
from wekker.background import BackgroundWorker
from wekker.button.controller import ButtonController
from wekker.clock import SystemClock
from wekker.cloud import CloudSettingsManager, DEFAULT_CLOUD_URL
from wekker.display.backlight import BacklightController
from wekker.display.manager import DisplayManager
from wekker.hardware.interfaces import Button, DisplayDriver, Lamp, Speaker
from wekker.hardware.mock import MockButton, MockDisplay, MockLamp, MockSpeaker
from wekker.logging_config import setup_logging
from wekker.settings import Settings, SettingsError, default_settings
from wekker.storage import JsonStore, StorageError

log = logging.getLogger(__name__)


@dataclass
class Runtime:
    ctx: AppContext
    button: Button
    controller: ButtonController
    speaker: Speaker
    lamp: Lamp
    driver: DisplayDriver
    backlight: BacklightController | None = None
    background: BackgroundWorker | None = None


def load_settings(store: JsonStore) -> Settings:
    try:
        data = store.load()
    except StorageError as exc:
        log.warning("instellingen onleesbaar, defaults gebruikt: %s", exc)
        return default_settings()
    if data is None:
        return default_settings()
    try:
        return Settings.from_dict(data)
    except SettingsError as exc:
        log.warning("ongeldig instellingenbestand, defaults gebruikt: %s", exc)
        return default_settings()


def _sidecar(settings_path: str | Path, name: str) -> Path:
    return Path(settings_path).resolve().with_name(name)


def build_default(
    settings_path: str | Path = "wekker-settings.json", *, enable_cloud: bool = False
) -> Runtime:
    store = JsonStore(settings_path)
    settings = load_settings(store)
    clock = SystemClock(settings.locale.timezone)

    cloud = None
    if enable_cloud:
        cloud = CloudSettingsManager(
            base_url=os.environ.get("WEKKER_CLOUD_URL", DEFAULT_CLOUD_URL),
            state_path=_sidecar(settings_path, ".wekker-cloud.json"),
        )

    speaker, lamp = MockSpeaker(), MockLamp()
    display_driver = MockDisplay()
    button = MockButton()
    cache = AgendaCache(path=_sidecar(settings_path, ".wakesync-agenda-cache.json"))
    display = DisplayManager(display_driver, settings, clock, cache)

    def _wake_on_ring(_old: AlarmState, new: AlarmState) -> None:
        if new is AlarmState.RINGING:
            display.button_pressed()

    core = AlarmClock(
        settings,
        clock,
        speaker,
        lamp,
        on_state_change=_wake_on_ring,
        runtime_store=AlarmRuntimeStore(_sidecar(settings_path, ".wakesync-alarm.json")),
    )
    auth = AuthService(clock, providers={"osiris": MockEntreeAuth(clock)})
    myx_auth = MyXAuthManager()
    try:
        sync = build_sync_provider(settings.agenda.provider, cache, clock, auth, myx_auth)
    except Exception as exc:
        log.warning("agenda-provider niet beschikbaar, mock gebruikt: %s", exc)
        sync = build_sync_provider("mock", cache, clock, auth, myx_auth)

    controller = ButtonController(core, lamp, display, clock, settings)
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
        backlight=BacklightController(),
        background=BackgroundWorker(),
    )


def _candidate_sync_provider(rt: Runtime, settings: Settings):
    return build_sync_provider(
        settings.agenda.provider,
        rt.ctx.cache,
        rt.ctx.clock,
        rt.ctx.auth,
        rt.ctx.myx_auth,
    )


def apply_runtime_settings(rt: Runtime, nieuwe: Settings) -> None:
    """Sla instellingen transactioneel op en pas ze daarna live toe.

    Bij een opslag- of runtimefout blijft de vorige geldige configuratie actief.
    Een provider wordt vóór de commit gebouwd zodat een ongeldige provider geen
    half toegepaste instelling kan achterlaten.
    """
    ctx = rt.ctx
    oude = ctx.settings
    oude_sync = ctx.sync
    provider_changed = nieuwe.agenda.provider != oude.agenda.provider
    candidate_sync = _candidate_sync_provider(rt, nieuwe) if provider_changed else oude_sync

    # Eerst atomisch naar schijf. Bij falen is nog niets in de runtime veranderd.
    ctx.store.save(nieuwe.to_dict())

    try:
        ctx.core.update_settings(nieuwe)
        ctx.display.update_settings(nieuwe)
        ctx.button.update_settings(nieuwe)
        set_timezone = getattr(ctx.clock, "set_timezone", None)
        if callable(set_timezone):
            set_timezone(nieuwe.locale.timezone)
        ctx.sync = candidate_sync
        ctx.settings = nieuwe
    except Exception:
        log.exception("runtime-instellingen toepassen faalde; oude configuratie hersteld")
        try:
            ctx.core.update_settings(oude)
            ctx.display.update_settings(oude)
            ctx.button.update_settings(oude)
            set_timezone = getattr(ctx.clock, "set_timezone", None)
            if callable(set_timezone):
                set_timezone(oude.locale.timezone)
            ctx.sync = oude_sync
            ctx.settings = oude
            ctx.store.save(oude.to_dict())
        except Exception:
            log.exception("rollback van instellingen was onvolledig")
        raise

    if rt.backlight is not None:
        set_async = getattr(rt.backlight, "set_percent_async", None)
        if callable(set_async):
            set_async(nieuwe.display.brightness)
        else:
            try:
                rt.backlight.set_percent(nieuwe.display.brightness)
            except Exception:
                log.exception("helderheidsdriver kon instelling niet toepassen")


def _apply_cloud_feed_update(rt: Runtime, update: dict) -> None:
    """Verwerk één MyX-feedopdracht synchroon.

    Productiecode plant dit werk via :class:`BackgroundWorker`; deze helper
    bevat dezelfde commitlogica voor herstelpaden en gerichte tests. Er wordt
    pas een ACK gestuurd nadat de feed lokaal is opgeslagen en de provider
    succesvol is vernieuwd.
    """
    auth = getattr(rt.ctx, "myx_auth", None)
    if auth is None:
        raise RuntimeError("MyX-authopslag ontbreekt")

    update_id = str(update.get("id") or "")
    action = str(update.get("action") or "")
    if not update_id or action not in {"set", "clear"}:
        raise ValueError("ongeldige feedopdracht")

    if action == "set":
        auth.save_feed(str(update.get("url") or ""))
        if rt.ctx.settings.agenda.provider != "myx":
            nieuwe = rt.ctx.settings.update_from_dict({"agenda": {"provider": "myx"}})
            apply_runtime_settings(rt, nieuwe)
        else:
            rt.ctx.sync = _candidate_sync_provider(rt, rt.ctx.settings)
    else:
        auth.feed_store.clear()
        rt.ctx.sync = _candidate_sync_provider(rt, rt.ctx.settings)

    cloud = getattr(rt.ctx, "cloud", None)
    if cloud is not None:
        cloud.acknowledge_feed_update(update_id)


def _queue_feed_update(rt: Runtime, update: dict) -> None:
    worker = rt.background
    auth = getattr(rt.ctx, "myx_auth", None)
    if worker is None or auth is None:
        return
    update_id = str(update.get("id") or "")
    action = str(update.get("action") or "")
    if not update_id or action not in {"set", "clear"}:
        return

    def job() -> dict:
        if action == "set":
            auth.save_feed(str(update.get("url") or ""))
        else:
            auth.feed_store.clear()
        return dict(update)

    if not worker.submit(f"feed:{update_id}", job):
        log.debug("feedtaak %s was al gepland", update_id)


def _handle_background_results(rt: Runtime) -> None:
    worker = rt.background
    if worker is None:
        return
    for result in worker.poll():
        if result.key == "agenda-sync":
            if not result.ok:
                log.error("agenda-achtergrondtaak faalde: %s", result.error)
            continue

        if result.key.startswith("feed:"):
            if not result.ok:
                log.error("MyX-feedopslag faalde: %s", result.error)
                continue
            update = result.value or {}
            try:
                if str(update.get("action")) == "set":
                    if rt.ctx.settings.agenda.provider != "myx":
                        nieuwe = rt.ctx.settings.update_from_dict(
                            {"agenda": {"provider": "myx"}}
                        )
                        apply_runtime_settings(rt, nieuwe)
                    else:
                        rt.ctx.sync = _candidate_sync_provider(rt, rt.ctx.settings)
                else:
                    rt.ctx.sync = _candidate_sync_provider(rt, rt.ctx.settings)
            except Exception:
                log.exception("provider kon na feedupdate niet worden vernieuwd")
                continue
            cloud = getattr(rt.ctx, "cloud", None)
            if cloud is not None:
                cloud.acknowledge_feed_update(str(update.get("id") or ""))
            log.info("MyX-feedopdracht lokaal verwerkt en ACK gepland")


def run_once(rt: Runtime) -> None:
    """Eén snelle wekker-/GUI-tik; netwerkwerk wordt alleen ingepland."""
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
    _handle_background_results(rt)
    maybe_auto_sync(rt)
    maybe_cloud_sync(rt)


def _update_display_context(rt: Runtime) -> None:
    try:
        nxt = rt.ctx.core.next_alarm()
        rt.ctx.display.set_alarm_context(
            rt.ctx.core.state.value,
            nxt.strftime("%H:%M") if nxt else None,
        )
    except Exception:
        log.exception("display-context bijwerken faalde")


def maybe_auto_sync(rt: Runtime) -> bool:
    """Plan agenda-sync zonder de alarm-/GUI-thread te blokkeren.

    Returnwaarde betekent in v8: ``True`` als een taak is ingepland.
    """
    minutes = rt.ctx.settings.agenda.auto_sync_minutes
    if minutes <= 0:
        return False

    from datetime import timedelta
    last_attempt = getattr(rt.ctx.cache, "last_attempt", None)
    if last_attempt is not None:
        try:
            if rt.ctx.clock.now() - last_attempt < timedelta(minutes=minutes):
                return False
        except TypeError:
            pass

    worker = getattr(rt, "background", None)
    if worker is None:
        # Alleen voor eenvoudige unit-testdoubles/legacy CLI.
        return bool(rt.ctx.sync.sync_default_window())

    if worker.has_pending("agenda-sync"):
        return False
    return worker.submit("agenda-sync", rt.ctx.sync.sync_default_window)


def maybe_cloud_sync(rt: Runtime) -> None:
    cloud = getattr(rt.ctx, "cloud", None)
    if cloud is None:
        return

    patch = cloud.consume_remote_patch()
    if patch:
        try:
            nieuwe = rt.ctx.settings.update_from_dict(patch)
            apply_runtime_settings(rt, nieuwe)
            cloud.acknowledge_remote_patch(rt.ctx.settings)
            log.info("cloudinstellingen toegepast en bevestigd")
        except Exception:
            try:
                cloud.reject_remote_patch()
            except Exception:
                log.exception("remote cloudpatch kon niet worden vrijgegeven")
            log.exception("cloudinstellingen waren ongeldig en worden opnieuw opgehaald")

    feed_update = cloud.consume_feed_update()
    if feed_update:
        _queue_feed_update(rt, feed_update)

    try:
        cloud.maybe_sync(rt.ctx.settings)
    except Exception:
        log.exception("cloudsync kon niet worden gestart")


def shutdown(rt: Runtime) -> None:
    try:
        rt.controller.shutdown()
    except Exception:
        log.exception("lamp uitschakelen bij shutdown faalde")
    if rt.background is not None:
        rt.background.close()


def _run_touch_setup(args: argparse.Namespace) -> int:
    from wekker.touch_setup import TouchConfigurator, TouchSetupError

    manager = TouchConfigurator(home=args.home or None)
    try:
        if args.status:
            status = manager.detect()
        elif args.verify:
            status = manager.verify_after_boot()
        else:
            status = manager.apply(
                profile=args.profile,
                confirmed=bool(args.confirmed),
            )
    except TouchSetupError as exc:
        print(f"fout: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(status.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _run_healthcheck(settings_path: str) -> int:
    """Expliciete app-healthcheck voor de updater, zonder netwerk of GUI."""
    try:
        store = JsonStore(settings_path)
        settings = load_settings(store)
        clock = SystemClock(settings.locale.timezone)
        # Imports en kernobjecten moeten bruikbaar zijn.
        from wekker.gui.screens import SCREEN_HEIGHT, SCREEN_WIDTH
        from wekker import __version__
        assert SCREEN_WIDTH == 800 and SCREEN_HEIGHT == 480
        payload = {
            "ok": True,
            "service": "wakesync",
            "version": __version__,
            "timezone": settings.locale.timezone,
            "now": clock.now().isoformat(),
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 1


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="WakeSync slimme schoolwekker")
    sub = parser.add_subparsers(dest="command")

    sim_p = sub.add_parser("simulate", help="lokale simulatie met bestuurbare tijd")
    sim_p.add_argument("--start", default="07:29:50")
    sim_p.add_argument("--day", default="2026-09-17")
    sim_p.add_argument("--alarm", default="07:30")
    sim_p.add_argument("--snooze", type=int, default=5)
    sim_p.add_argument("--lampdur", type=int, default=30)
    sim_p.add_argument("--commands", default=None)
    sim_p.add_argument("--demo", action="store_true")

    gui_p = sub.add_parser("gui", help="fullscreen touchscreen-GUI (800x480)")
    gui_p.add_argument("--window", action="store_true")
    gui_p.add_argument("--host", default=None, help=argparse.SUPPRESS)
    gui_p.add_argument("--port", type=int, default=None, help=argparse.SUPPRESS)
    gui_p.add_argument("--settings", default="wekker-settings.json")

    health_p = sub.add_parser("healthcheck", help="lokale update-healthcheck")
    health_p.add_argument("--settings", default="wekker-settings.json")

    touch_p = sub.add_parser("touch-setup", help="Waveshare touch/display configureren")
    touch_p.add_argument("--profile", default="waveshare-5-hdmi-ads7846")
    touch_p.add_argument("--confirmed", action="store_true",
                         help="bevestig profiel als ADS7846 nog niet gedetecteerd is")
    touch_p.add_argument("--status", action="store_true")
    touch_p.add_argument("--verify", action="store_true")
    touch_p.add_argument("--home", default=None, help="gebruikers-home voor labwc rc.xml")

    args = parser.parse_args(argv)
    setup_logging()

    if args.command == "simulate":
        run_simulate(args)
        return
    if args.command == "gui":
        run_gui(args)
        return
    if args.command == "healthcheck":
        raise SystemExit(_run_healthcheck(args.settings))
    if args.command == "touch-setup":
        raise SystemExit(_run_touch_setup(args))
    parser.print_help()


def run_gui(args: argparse.Namespace) -> None:
    from wekker.gui.app import launch_gui
    try:
        rt = build_default(args.settings, enable_cloud=True)
    except StorageError as exc:
        log.error("opslagfout: %s", exc)
        raise SystemExit(1) from exc

    rt.backlight = BacklightController()
    rt.backlight.set_percent_async(rt.ctx.settings.display.brightness)
    try:
        launch_gui(rt, fullscreen=not args.window)
    except KeyboardInterrupt:
        log.info("stoppen…")
    finally:
        shutdown(rt)


def run_simulate(args: argparse.Namespace) -> None:
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
