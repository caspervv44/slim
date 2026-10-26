"""WakeSync starten vanaf bureaublad, autostart of terminal.

Alle grafische starts gebruiken de eigen projectmap, virtuele omgeving en een
absoluut instellingenpad. Geen sudo, xhost of wijzigingen aan touchkalibratie.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time


class LaunchError(RuntimeError):
    """Een voor de gebruiker verklaarbare startfout."""


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def private_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.stat().st_uid != os.getuid():
        raise LaunchError(f"Onveilige of niet-eigen map: {path}")
    os.chmod(path, 0o700)
    return path


def state_directory() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    return private_directory(base / "wakesync")


def runtime_directory() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    return private_directory(base / "wakesync")


def process_environment(process: Path) -> dict[str, str]:
    return dict(
        part.decode("utf-8", "replace").split("=", 1)
        for part in (process / "environ").read_bytes().split(b"\0") if b"=" in part
    )


DISPLAY_KEYS = (
    "DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS", "XDG_CURRENT_DESKTOP",
)


def local_display_environment(
    environment: dict[str, str], proc_root: Path = Path("/proc"), uid: int | None = None,
) -> dict[str, str]:
    """Vind alleen een lokale grafische sessie van dezelfde Linux-gebruiker."""
    uid = os.getuid() if uid is None else uid
    env = dict(environment)
    if env.get("DISPLAY", "").startswith(":") and not env.get("SSH_CONNECTION"):
        return env
    candidates: dict[str, tuple[tuple[bool, bool], dict[str, str]]] = {}
    xwaylands: dict[str, dict[str, str]] = {}
    try:
        processes = list(proc_root.iterdir())
    except OSError as exc:
        raise LaunchError("De lokale desktopsessie kon niet worden gelezen.") from exc
    for process in processes:
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != uid or int(process.name) == os.getpid():
                continue
            name = (process / "comm").read_text().strip()
            candidate = process_environment(process)
            display = candidate.get("DISPLAY", "")
            desktop_client = name in ("pcmanfm", "pcmanfm-qt", "wf-panel-pi", "waybar", "lxsession")
            if display.startswith(":") and (candidate.get("WAYLAND_DISPLAY") or desktop_client):
                score = (bool(candidate.get("XAUTHORITY")), desktop_client)
                if display not in candidates or score > candidates[display][0]:
                    candidates[display] = (score, candidate)
            if name.lower() == "xwayland":
                args = [a.decode("utf-8", "replace")
                        for a in (process / "cmdline").read_bytes().split(b"\0") if a]
                displays = [a for a in args if re.fullmatch(r":\d+", a)]
                if displays:
                    values = {
                        "DISPLAY": displays[0],
                        "XDG_RUNTIME_DIR": candidate.get("XDG_RUNTIME_DIR", f"/run/user/{uid}"),
                    }
                    if "-auth" in args:
                        values["XAUTHORITY"] = args[args.index("-auth") + 1]
                    xwaylands[displays[0]] = values
        except (OSError, ValueError, IndexError):
            continue
    if len(candidates) == 1:
        selected = next(iter(candidates.values()))[1]
    elif not candidates and len(xwaylands) == 1:
        selected = next(iter(xwaylands.values()))
    elif len(candidates) > 1 or len(xwaylands) > 1:
        raise LaunchError("Meerdere lokale displays gevonden. Start WakeSync op het Pi-bureaublad.")
    else:
        raise LaunchError(
            "Geen lokaal Pi-bureaublad gevonden. Log eerst grafisch in; "
            "WakeSync kan niet op een uitsluitend tekstuele sessie verschijnen."
        )
    for key in DISPLAY_KEYS:
        if selected.get(key):
            env[key] = selected[key]
        else:
            env.pop(key, None)
    return env


def build_command(repo: Path, settings: str | None = None, window: bool = False) -> list[str]:
    repo = repo.resolve()
    python = repo / ".venv/bin/python"
    if not python.is_file():
        raise LaunchError(f"Virtuele omgeving ontbreekt: {python}")
    if not (repo / "src/wekker/gui/app.py").is_file():
        raise LaunchError("Dit is geen volledige WakeSync-repository.")
    settings_path = Path(settings).expanduser() if settings else repo / "wekker-settings.json"
    if not settings_path.is_absolute():
        settings_path = repo / settings_path
    settings_path = settings_path.resolve()
    # Niet ongemerkt een nieuwe lege configuratie maken door een verkeerde map.
    if not settings_path.is_file():
        raise LaunchError(
            f"Instellingen ontbreken: {settings_path}\n"
            "Gebruik --settings met het bestaande bestand van je werkende wekker."
        )
    command = [str(python), "-m", "wekker", "gui", "--settings", str(settings_path)]
    if window:
        command.append("--window")
    return command


@contextmanager
def single_instance(directory: Path):
    """Bestandslock blijft vast zolang het door ons gestarte GUI-proces draait."""
    import fcntl
    path = directory / "desktop.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or not stat.S_ISREG(info.st_mode):
            raise LaunchError("Het WakeSync-lockbestand is niet veilig.")
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            os.ftruncate(fd, 0)
            os.write(fd, str(os.getpid()).encode("ascii"))
            try:
                yield True
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def request_focus(directory: Path) -> None:
    path = directory / "focus-request"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, str(time.time_ns()).encode("ascii"))
    finally:
        os.close(fd)


def other_gui_running(proc_root: Path = Path("/proc")) -> bool:
    """Ook een eerder handmatig gestarte `python -m wekker gui` niet dupliceren."""
    for process in proc_root.iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            args = [a.decode("utf-8", "replace")
                    for a in (process / "cmdline").read_bytes().split(b"\0") if a]
            if any(args[i:i+3] == ["-m", "wekker", "gui"]
                   for i in range(max(0, len(args)-2))):
                return True
            if args and Path(args[0]).name in ("wekker", "wakesync-gui") and "gui" in args[1:]:
                return True
        except OSError:
            continue
    return False


def validate_gui_routes() -> None:
    """Controle van de echte, lokaal geïnstalleerde handlers zonder Tk-venster."""
    from wekker.gui.app import TouchApp
    from wekker.gui.premium import PremiumTouchApp
    from wekker.gui.settings_routes_v1021 import ROUTES
    for section in ("software", "diagnostics"):
        method = ROUTES[section]["method"]
        if not callable(getattr(PremiumTouchApp, method, None)):
            raise LaunchError(f"{section}: schermfunctie {method} ontbreekt.")
    if not issubclass(PremiumTouchApp, TouchApp):
        raise LaunchError("De premium-interface sluit niet aan op de bestaande GUI.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start WakeSync op het lokale Pi-scherm")
    parser.add_argument("--window", action="store_true", help="Start als venster")
    parser.add_argument("--settings", help="Bestaand instellingenbestand; standaard in projectmap")
    parser.add_argument("--autostart", action="store_true", help="Start vanuit de desktopsessie")
    parser.add_argument("--check", action="store_true", help="Controleer installatie, start geen GUI")
    parser.add_argument("--version", action="store_true", help="Toon geïnstalleerde bronversie")
    args = parser.parse_args(argv)
    try:
        from wekker import __version__
        if args.version:
            print(f"WakeSync {__version__}")
            return 0
        if os.geteuid() == 0:
            raise LaunchError("Start WakeSync als je gewone gebruiker, niet met sudo.")
        repo = project_root()
        command = build_command(repo, args.settings, args.window)
        validate_gui_routes()
        if args.check:
            print(f"WakeSync-versie: {__version__}")
            print(f"Projectmap: {repo}")
            print(f"Python: {command[0]}")
            print(f"Instellingen: {command[5]}")
            print("Software- en Diagnose-functies: aanwezig")
            print("Touchkalibratie: niet aangepast")
            return 0
        directory = runtime_directory()
        with single_instance(directory) as acquired:
            if not acquired:
                if not args.autostart:
                    request_focus(directory)
                    print("WakeSync draait al; venster gevraagd naar voren.")
                return 0
            if other_gui_running():
                print("WakeSync draait al buiten deze starter. Sluit dat venster eerst.")
                return 0
            # Hergebruik voor SSH de sessiedetectie van de werkende touch-meettool.
            environment = local_display_environment(dict(os.environ))
            environment["WAKESYNC_FOCUS_FILE"] = str(directory / "focus-request")
            environment["PYTHONUNBUFFERED"] = "1"
            logfile = state_directory() / "gui.log"
            if logfile.is_symlink():
                raise LaunchError("Onveilig logpad.")
            if logfile.exists() and logfile.stat().st_size > 2_000_000:
                logfile.replace(logfile.with_suffix(".log.1"))
            flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(logfile, flags, 0o600)
            with os.fdopen(fd, "ab") as log:
                log.write(f"\n--- WakeSync {__version__} start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n".encode())
                log.flush()
                print(f"WakeSync opent op {environment['DISPLAY']}. Log: {logfile}", flush=True)
                child = subprocess.Popen(
                    command, cwd=repo, env=environment, stdout=log, stderr=log,
                    start_new_session=True,
                )
                try:
                    result = child.wait()
                except KeyboardInterrupt:
                    child.send_signal(signal.SIGTERM)
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
                    return 130
            if result:
                print(f"WakeSync stopte met code {result}. Bekijk het lokale log: {logfile}", file=sys.stderr)
            return max(0, result) if result >= 0 else 1
    except (LaunchError, OSError, ValueError, KeyError, ImportError) as exc:
        print(f"WakeSync kan niet starten: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
