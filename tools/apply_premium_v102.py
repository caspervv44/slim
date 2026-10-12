#!/usr/bin/env python3
"""Veilige WakeSync-v10.2 installatie in de al bestaande GitHub-clone.

Alleen drie kleine bestaande Python/metadata-bestanden worden aangepast.
Originele versies en herstelmanifest staan buiten de Git-repository.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

MARKER_START = "    # [WakeSync Premium] BEGIN\n"
MARKER_END = "    # [WakeSync Premium] EINDE\n"
MARKER_CODE = (
    MARKER_START
    + "    from wekker.gui.premium import PremiumTouchApp\n"
    + "    app = PremiumTouchApp(root, runtime)\n"
    + MARKER_END
)
OLD_GUI_ENTRY = "    app = TouchApp(root, runtime)\n"
OLD_AUDIO = "    speaker, lamp = MockSpeaker(), MockLamp()\n"
NEW_AUDIO = "    speaker, lamp = make_speaker(), MockLamp()\n"
AUDIO_IMPORT = "from wekker.hardware.audio import make_speaker\n"
CURRENT = "10.1.1"
NEW_VERSION = "10.2.0"


class InstallError(RuntimeError):
    pass


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _backup_dir(repo: Path) -> Path:
    token = hashlib.sha256(str(repo.resolve()).encode()).hexdigest()[:16]
    return Path.home() / ".local/share/wakesync-premium-v102" / token


def _atomic_write(path: Path, content: bytes) -> None:
    mode = path.stat().st_mode & 0o777
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=".wakesync-", suffix=".tmp", delete=False,
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    try:
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _make_changes(repo: Path) -> dict[str, tuple[bytes, bytes]]:
    necessary = [
        "src/wekker/gui/premium.py",
        "src/wekker/gui/premium_render.py",
        "src/wekker/hardware/audio.py",
        "src/wekker/assets/premium_midnight.png",
        "src/wekker/assets/premium_ocean.png",
        "src/wekker/assets/premium_light.png",
        "src/wekker/assets/premium_amber.png",
        "src/wekker/assets/wakesync-logo.png",
        "src/wekker/gui/app.py",
        "src/wekker/main.py",
        "src/wekker/__init__.py",
        "pyproject.toml",
    ]
    for name in necessary:
        if not (repo / name).is_file():
            raise InstallError(f"Bestand ontbreekt: {name}")

    init = (repo / "src/wekker/__init__.py").read_text(encoding="utf8")
    match = re.search(r'(?m)^__version__\s*=\s*"([^"]+)"\s*$', init)
    if not match or match.group(1) not in {CURRENT, NEW_VERSION}:
        raise InstallError("De bronversie wijkt af van 10.1.1/10.2.0; geen wijzigingen.")
    current_version = match.group(1)
    if current_version == NEW_VERSION:
        # Controleer idempotentie in plaats van stilzwijgend een gedeeltelijke
        # installatie als geslaagd te presenteren.
        main = (repo / "src/wekker/main.py").read_text(encoding="utf8")
        gui = (repo / "src/wekker/gui/app.py").read_text(encoding="utf8")
        project = (repo / "pyproject.toml").read_text(encoding="utf8")
        if NEW_AUDIO not in main or AUDIO_IMPORT not in main or MARKER_CODE not in gui:
            raise InstallError("v10.2 vermeld maar installatie onvolledig; handmatig controleren.")
        if not re.search(r'(?m)^version\s*=\s*"10\.2\.0"\s*$', project):
            raise InstallError("v10.2 vermeld maar pyproject.toml wijkt af.")
        return {}

    changes: dict[str, tuple[bytes, bytes]] = {}

    def replace_file(name: str, before: str, after: str) -> None:
        if before != after:
            changes[name] = (before.encode("utf8"), after.encode("utf8"))

    main_name = "src/wekker/main.py"
    main = (repo / main_name).read_text(encoding="utf8")
    if main.count(OLD_AUDIO) != 1:
        raise InstallError("main.py is veranderd: verwacht de bestaande MockSpeaker-regel.")
    if AUDIO_IMPORT in main:
        raise InstallError("main.py bevat al de audiodriver; controleer versie en code.")
    anchor = "from wekker.hardware.mock import MockButton, MockDisplay, MockLamp, MockSpeaker\n"
    if main.count(anchor) != 1:
        raise InstallError("Onbekende importstructuur in main.py.")
    changed_main = main.replace(anchor, anchor + AUDIO_IMPORT, 1)
    changed_main = changed_main.replace(OLD_AUDIO, NEW_AUDIO, 1)
    replace_file(main_name, main, changed_main)

    gui_name = "src/wekker/gui/app.py"
    gui = (repo / gui_name).read_text(encoding="utf8")
    if MARKER_CODE in gui and gui.count(MARKER_START) == 1 and gui.count(MARKER_END) == 1:
        pass  # Is al geactiveerd door het eerder uitgeleverde premium-pakket.
    elif MARKER_START not in gui and MARKER_END not in gui and gui.count(OLD_GUI_ENTRY) == 1:
        replace_file(gui_name, gui, gui.replace(OLD_GUI_ENTRY, MARKER_CODE, 1))
    else:
        raise InstallError("De grafische startup is aangepast; geen bronbestanden overschreven.")

    init_name = "src/wekker/__init__.py"
    changed_init = init.replace('__version__ = "10.1.1"', '__version__ = "10.2.0"', 1)
    replace_file(init_name, init, changed_init)

    project_name = "pyproject.toml"
    project = (repo / project_name).read_text(encoding="utf8")
    project_after, count = re.subn(
        r'(?m)^(version\s*=\s*")10\.1\.1("\s*)$', rf'\g<1>{NEW_VERSION}\g<2>',
        project,
    )
    if count != 1:
        raise InstallError("pyproject.toml heeft een andere pakketversie; geen wijzigingen.")
    replace_file(project_name, project, project_after)
    return changes


def apply(repo: Path | None = None, backup_dir: Path | None = None) -> int:
    repo = (repo or _repo_root()).resolve()
    backup = backup_dir or _backup_dir(repo)
    try:
        changes = _make_changes(repo)
        if not changes:
            print("WakeSync v10.2.0 is al geactiveerd; geen wijzigingen.")
            return 0
        if backup.exists() and (backup / "manifest.json").exists():
            raise InstallError("Er staat al een v10.2-backup. Controleer eerst de bronwijzigingen.")

        # Alle wijzigingen zijn vooraf gecontroleerd. Vanaf hier pas schrijven.
        backup.mkdir(parents=True, exist_ok=True)
        manifest = {}
        for name, (before, after) in changes.items():
            original = backup / "original" / name
            original.parent.mkdir(parents=True, exist_ok=True)
            original.write_bytes(before)
            manifest[name] = {"old": _hash(before), "new": _hash(after)}

        written = []
        try:
            for name, (_before, after) in changes.items():
                _atomic_write(repo / name, after)
                written.append(name)
            (backup / "manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf8",
            )
        except Exception:
            for name in reversed(written):
                _atomic_write(repo / name, changes[name][0])
            raise

        print("WakeSync Premium v10.2.0 geactiveerd.")
        print("Backups buiten de repo:", backup)
        print("Test eerst: python3 -m compileall -q src tests tools")
        print("Daarna: python3 -m pytest -q")
        return 0
    except (OSError, InstallError) as exc:
        print(f"Veiligheidsstop: {exc}", file=sys.stderr)
        return 2


def revert(repo: Path | None = None, backup_dir: Path | None = None) -> int:
    repo = (repo or _repo_root()).resolve()
    backup = backup_dir or _backup_dir(repo)
    manifest_file = backup / "manifest.json"
    if not manifest_file.is_file():
        print("Geen herstelmanifest aanwezig; niets gewijzigd.", file=sys.stderr)
        return 2
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf8"))
        originals = {}
        for name, hashes in manifest.items():
            current = (repo / name).read_bytes()
            old = (backup / "original" / name).read_bytes()
            if _hash(current) != hashes["new"] or _hash(old) != hashes["old"]:
                raise InstallError(f"{name} is later aangepast; herstel is gestopt.")
            originals[name] = old
        for name, data in originals.items():
            _atomic_write(repo / name, data)
        # Vervang de bestaande Premium-modules desgewenst via git restore op Pi.
        print("Oorspronkelijke bronbestanden hersteld; herinstalleer daarna je package.")
        return 0
    except (OSError, KeyError, ValueError, InstallError) as exc:
        print(f"Veiligheidsstop bij herstel: {exc}", file=sys.stderr)
        return 2


def main() -> None:
    raise SystemExit(apply())


if __name__ == "__main__":
    main()
