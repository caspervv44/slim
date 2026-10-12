#!/usr/bin/env python3
"""Activeer de WakeSync MyX-agendaweergave-hotfix zonder alarmcode te veranderen."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

BEGIN = "# [WakeSync MyX Agenda Hotfix] BEGIN"
END = "# [WakeSync MyX Agenda Hotfix] EINDE"
BLOCK = (
    f"{BEGIN}\n"
    "from wekker.gui.agenda_fix import install_agenda_fix\n"
    "install_agenda_fix(TouchApp)\n"
    f"{END}\n\n"
)
ANCHOR = "def launch_gui(runtime: Any, fullscreen: bool = True) -> None:"
FILE = Path("src/wekker/gui/app.py")


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _backup_dir(repo: Path) -> Path:
    token = _hash(str(repo.resolve()).encode())[:16]
    return Path.home() / ".local/share/wakesync-myx-agenda-hotfix" / token


def _write_atomically(path: Path, data: bytes) -> None:
    mode = path.stat().st_mode & 0o777
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=".wakesync-agenda-", delete=False
    ) as tmp:
        tmp.write(data)
        temp = Path(tmp.name)
    try:
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def apply(repo: Path | None = None, backup: Path | None = None) -> int:
    repo = (repo or Path(__file__).resolve().parents[1]).resolve()
    source_path = repo / FILE
    fix_module = repo / "src/wekker/gui/agenda_fix.py"
    backup = backup or _backup_dir(repo)
    if not source_path.is_file() or not fix_module.is_file():
        print("STOP: app.py of agenda_fix.py ontbreekt. Pak de ZIP eerst uit in de repo.", file=sys.stderr)
        return 2
    try:
        before = source_path.read_bytes()
        text = before.decode("utf-8")
        if BEGIN in text or END in text:
            if text.count(BEGIN) == 1 and text.count(END) == 1 and BLOCK in text:
                print("Agendareparatie was al geactiveerd; niets gewijzigd.")
                return 0
            print("STOP: er bestaat al een afwijkende agendareparatie.", file=sys.stderr)
            return 2

        if text.count(ANCHOR) != 1 or "class TouchApp:" not in text:
            print("STOP: onbekende WakeSync-GUI-versie. app.py niet overschreven.", file=sys.stderr)
            return 2
        # Zo wordt de bestaande PremiumTouchApp automatisch meegenomen:
        # zijn basisklasse is TouchApp, die we hieronder uitbreiden.
        after = text.replace(ANCHOR, BLOCK + ANCHOR, 1)
        ast.parse(after, filename=str(source_path))
        ast.parse(fix_module.read_text(encoding="utf-8"), filename=str(fix_module))
        if (backup / "manifest.json").exists():
            print("STOP: er bestaat al een herstelmanifest voor deze repository.", file=sys.stderr)
            return 2

        backup.mkdir(parents=True, exist_ok=True)
        (backup / "app.py.origineel").write_bytes(before)
        (backup / "manifest.json").write_text(
            json.dumps({"before_sha256": _hash(before),
                        "after_sha256": _hash(after.encode("utf-8"))}, indent=2),
            encoding="utf-8",
        )
        _write_atomically(source_path, after.encode("utf-8"))
        print("GEREED: agenda toont voortaan automatisch een gevulde lesdag.")
        print("Er zijn geen alarm-, thema- of cachebestanden gewijzigd.")
        print("Herstelkopie:", backup)
        return 0
    except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
        print(f"STOP: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


def undo(repo: Path | None = None, backup: Path | None = None) -> int:
    repo = (repo or Path(__file__).resolve().parents[1]).resolve()
    backup = backup or _backup_dir(repo)
    try:
        manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
        source_path = repo / FILE
        current = source_path.read_bytes()
        original = (backup / "app.py.origineel").read_bytes()
        if _hash(current) != manifest["after_sha256"]:
            raise ValueError("app.py is inmiddels veranderd; automatisch terugzetten gestopt")
        if _hash(original) != manifest["before_sha256"]:
            raise ValueError("herstelkopie is gewijzigd")
        _write_atomically(source_path, original)
        print("app.py hersteld. agenda_fix.py mag blijven staan; wordt niet geladen.")
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"Herstel niet mogelijk: {exc}", file=sys.stderr)
        return 2


def main() -> None:
    parser = argparse.ArgumentParser(description="WakeSync agendaweergave repareren")
    parser.add_argument("--undo", action="store_true", help="Herstel app.py veilig")
    args = parser.parse_args()
    raise SystemExit(undo() if args.undo else apply())


if __name__ == "__main__":
    main()
