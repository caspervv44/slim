#!/usr/bin/env python3
"""Installeer alleen de persoonlijke WakeSync-snelkoppeling en autostart.

Gebruik op de Raspberry Pi, zonder sudo:
    python3 tools/install_wakesync_desktop.py --install --autostart
Kalibratie, rc.xml, overlays, wekkerinstellingen en feed worden niet geschreven.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

from wakesync_install_common import apply_transaction, restore_transaction

ROOT = Path(__file__).resolve().parents[1]
START = "# BEGIN WAKESYNC STARTER 10.2.1"
END = "# END WAKESYNC STARTER 10.2.1"


def string_value(value: str) -> str:
    if any(c in value for c in "\n\r\0"):
        raise ValueError("Nieuwe regel of NUL is niet toegestaan in een pad.")
    return value.replace("\\", "\\\\")


def exec_arg(value: str) -> str:
    """Escape volgens Desktop Entry: niet volgens een willekeurige shell."""
    if any(c in value for c in "\n\r\0"):
        raise ValueError("Ongeldig pad voor de snelkoppeling.")
    value = value.replace("%", "%%")
    value = value.replace("\\", "\\\\\\\\")
    for character in ('"', "`", "$"):
        value = value.replace(character, "\\\\" + character)
    return '"' + value + '"'


def managed_block(original: str, body: str | None) -> str:
    if original.count(START) != original.count(END) or original.count(START) > 1:
        raise ValueError("Onvolledig of dubbel WakeSync-startblok; niets overschrijven.")
    new_block = f"{START}\n{body.rstrip()}\n{END}" if body is not None else ""
    if START in original:
        start = original.index(START)
        end = original.index(END) + len(END)
        return original[:start] + new_block + original[end:]
    if body is None:
        return original
    return original.rstrip("\n") + ("\n\n" if original else "") + new_block + "\n"


def desktop_contents(repo: Path, wrapper: Path, *, autostart: bool = False) -> str:
    icon = repo / "src/wekker/assets/wakesync-logo.png"
    text = (
        "[Desktop Entry]\nType=Application\nVersion=1.0\nName=WakeSync\n"
        "Comment=Tijd, agenda en alarmen op je Raspberry Pi\n"
        f"Exec={exec_arg(str(wrapper))}" + (" --autostart" if autostart else "") + "\n"
        f"TryExec={string_value(str(wrapper))}\n"
        f"Path={string_value(str(repo))}\n"
        f"Icon={string_value(str(icon)) if icon.is_file() else 'appointment-new'}\n"
        "Terminal=false\nStartupNotify=false\nCategories=Utility;\nX-WakeSync-Managed=true\n"
    )
    if not autostart:
        text += (
            "Actions=Projectmap;\n\n[Desktop Action Projectmap]\n"
            "Name=Projectmap openen\n"
            f"Exec=xdg-open {exec_arg(str(repo))}\n"
        )
    return text


def desktop_directory(home: Path) -> Path:
    try:
        result = subprocess.run(
            ["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=3,
            check=True,
        ).stdout.strip()
        path = Path(result)
        if path.is_absolute() and path != home:
            return path
    except (OSError, subprocess.SubprocessError):
        pass
    return home / ("Bureaublad" if (home / "Bureaublad").is_dir() else "Desktop")


def labwc_merge_active(proc: Path = Path("/proc")) -> bool:
    for process in proc.iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            if (process / "comm").read_text().strip() != "labwc":
                continue
            args = (process / "cmdline").read_bytes().split(b"\0")
            return b"-m" in args or b"--merge-config" in args
        except OSError:
            continue
    return False


def make_plan(
    repo: Path, home: Path, desktop: Path, *, autostart: bool,
    config_home: Path | None = None, data_home: Path | None = None,
    merge_active: bool = False, system_autostart: Path | None = None,
) -> dict[Path, tuple[bytes | None, bytes, int]]:
    repo, home = repo.resolve(), home.resolve()
    if not (repo / ".venv/bin/python").is_file():
        raise ValueError("De eigen .venv/bin/python ontbreekt; maak/herstel de venv eerst.")
    if not (repo / "wekker-settings.json").is_file():
        raise ValueError(
            "wekker-settings.json ontbreekt in deze projectmap. "
            "Installeer de starter vanuit de werkende clone, niet vanuit een lege downloadmap."
        )
    for name in ("src/wekker/desktop.py", "tools/wakesync_launch.py"):
        if not (repo / name).is_file():
            raise ValueError(f"Update 10.2.1 is niet toegepast: {name} ontbreekt.")
    config_home = config_home or home / ".config"
    data_home = data_home or home / ".local/share"
    wrapper = home / ".local/bin/wakesync"
    changes = {}

    def put(path: Path, text: str, mode: int = 0o644):
        if path.is_symlink():
            raise ValueError(f"Symbolische link niet overschrijven: {path}")
        before = path.read_bytes() if path.exists() else None
        after = text.encode("utf-8")
        if before != after or (path.exists() and path.stat().st_mode & 0o777 != mode):
            changes[path] = (before, after, mode)

    wrapper_text = (
        "#!/bin/sh\n# WakeSync: vaste projectmap en eigen virtuele omgeving.\n"
        f"exec {shlex.quote(str(repo / '.venv/bin/python'))} "
        f"{shlex.quote(str(repo / 'tools/wakesync_launch.py'))} \"$@\"\n"
    )
    put(wrapper, wrapper_text, 0o755)
    content = desktop_contents(repo, wrapper)
    put(desktop / "WakeSync.desktop", content, 0o755)
    put(data_home / "applications/wakesync.desktop", content, 0o644)

    # De opdracht is na een nieuwe shell beschikbaar; bestaande PATH blijft staan.
    path_body = (
        'case ":$PATH:" in\n'
        '    *":$HOME/.local/bin:"*) ;;\n'
        '    *) export PATH="$HOME/.local/bin:$PATH" ;;\n'
        'esac'
    )
    shell_files = [home / ".profile", home / ".bashrc"]
    for extra in (home / ".bash_profile", home / ".bash_login"):
        if extra.exists():
            shell_files.append(extra)
    for path in shell_files:
        original = path.read_text(encoding="utf-8") if path.exists() else ""
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
        put(path, managed_block(original, path_body), mode)

    if autostart:
        # labwc is de desktop van deze Pi. Nooit rc.xml of touchinstellingen wijzigen.
        target = config_home / "labwc/autostart"
        original = target.read_text(encoding="utf-8") if target.exists() else "#!/bin/sh\n"
        if any(re.match(r"^\s*(exit|exec)\b", line) for line in original.splitlines()
               if not line.lstrip().startswith("#")):
            raise ValueError(
                "Bestaande labwc/autostart bevat exit/exec. Geen automatisch blok "
                "toevoegen achter een mogelijk eindpunt; laat het bestand eerst controleren."
            )
        prefix = ""
        if not target.exists() and not merge_active and system_autostart and system_autostart.is_file():
            # Zonder -m zou een nieuw gebruikersbestand de systeembestandketen vervangen.
            # Behoud in dat geval expliciet de bestaande panelen/bureaublad-start.
            prefix = (
                "# Behoud de bestaande systeemautostart zonder labwc --merge-config.\n"
                f". {shlex.quote(str(system_autostart))}\n"
            )
        # De systeemketen staat BUITEN ons verwijderbare startblok.
        body = f"{shlex.quote(str(wrapper))} --autostart &"
        if prefix:
            original = "#!/bin/sh\n" + prefix
        put(target, managed_block(original, body),
            target.stat().st_mode & 0o777 if target.exists() else 0o755)
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--install", action="store_true")
    choice.add_argument("--check", action="store_true")
    choice.add_argument("--disable-autostart", action="store_true")
    choice.add_argument("--restore", type=Path, help="Herstelmanifest van eerdere installatie")
    parser.add_argument("--autostart", action="store_true", help="Start ook na aanmelding op het labwc-bureaublad")
    args = parser.parse_args()
    try:
        if sys.platform != "linux":
            raise ValueError("Voer deze persoonlijke desktopinstallatie op de Raspberry Pi uit.")
        if os.geteuid() == 0:
            raise ValueError("Gebruik je gewone gebruiker, zonder sudo.")
        if args.restore:
            restore_transaction(args.restore)
            print("Persoonlijke startbestanden hersteld.")
            return 0
        home = Path.home()
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config")))
        data_home = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local/share")))
        # Voor en na verifiëren dat de gekalibreerde rc.xml bytegelijk blijft.
        calibration = config_home / "labwc/rc.xml"
        saved = calibration.read_bytes() if calibration.is_file() else None
        if args.disable_autostart:
            path = config_home / "labwc/autostart"
            original = path.read_bytes() if path.exists() else b""
            changed = managed_block(original.decode("utf-8"), None).encode("utf-8")
            changes = {} if changed == original else {
                path: (original, changed, path.stat().st_mode & 0o777)
            }
        else:
            system = next(
                (Path(p) / "labwc/autostart"
                 for p in os.environ.get("XDG_CONFIG_DIRS", "/etc/xdg").split(":")
                 if (Path(p) / "labwc/autostart").is_file()), None
            )
            changes = make_plan(
                ROOT, home, desktop_directory(home), autostart=args.autostart,
                config_home=config_home, data_home=data_home,
                merge_active=labwc_merge_active(), system_autostart=system,
            )
        for path in changes:
            print("Wijziging:", path)
        if args.check:
            print("Alleen gecontroleerd; niets geschreven.")
            return 0
        manifest = apply_transaction(changes, data_home / "wakesync-desktop-backups")
        if saved != (calibration.read_bytes() if calibration.is_file() else None):
            raise RuntimeError("rc.xml is tijdens de installatie door een ander proces gewijzigd.")
        print("Startvoorzieningen geïnstalleerd." if changes else "Alles staat al goed; niets gewijzigd.")
        if manifest:
            print("Herstelmanifest:", manifest)
        if not args.disable_autostart:
            desktop_file = desktop_directory(home) / "WakeSync.desktop"
            try:
                # Ondersteund door sommige desktops. Afwijzing maakt het bestand niet onbruikbaar.
                result = subprocess.run(
                    ["gio", "set", str(desktop_file), "metadata::trusted", "true"],
                    capture_output=True, timeout=3,
                )
                if result.returncode:
                    print("Bureaublad kan bij de eerste klik nog om 'Uitvoeren toestaan' vragen.")
            except (OSError, subprocess.SubprocessError):
                print("Bureaublad kan bij de eerste klik nog om 'Uitvoeren toestaan' vragen.")
            print('Huidige terminal: export PATH="$HOME/.local/bin:$PATH"; hash -r')
            print("Start: wakesync")
            if args.autostart:
                print("Autostart: na grafisch aanmelden. Desktop-autologin is niet gewijzigd.")
        print("Bestaande touchkalibratie is bytegelijk gebleven.")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Installatie gestopt: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
