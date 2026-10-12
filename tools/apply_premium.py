#!/usr/bin/env python3
"""Activeer WakeSync Premium op een lokale clone van caspervv44/slim.

Het script bewerkt precies één aanroep in gui/app.py, na automatische backup
buiten de git-repository. Alle gebruikersinstellingen blijven ongemoeid.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

OLD = "    app = TouchApp(root, runtime)\n"
START = "    # [WakeSync Premium] BEGIN\n"
END = "    # [WakeSync Premium] EINDE\n"
NEW = (
    START
    + "    from wekker.gui.premium import PremiumTouchApp\n"
    + "    app = PremiumTouchApp(root, runtime)\n"
    + END
)


def _root() -> Path:
    # tools/apply_premium.py -> git root
    return Path(__file__).resolve().parents[1]


def _backup_path(repo: Path) -> Path:
    key = hashlib.sha256(str(repo.resolve()).encode("utf-8")).hexdigest()[:16]
    return Path.home() / ".local/share/wakesync-premium" / key / "app.py.original"


def _atomic_write(path: Path, contents: bytes) -> None:
    mode = path.stat().st_mode & 0o777
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=".wakesync-", suffix=".tmp", delete=False
    ) as handle:
        handle.write(contents)
        temp = Path(handle.name)
    try:
        os.chmod(temp,mode)
        os.replace(temp,path)
    finally:
        temp.unlink(missing_ok=True)


def activate() -> int:
    repo = _root()
    file = repo / "src/wekker/gui/app.py"
    entry = repo / "src/wekker/gui/premium.py"
    artwork = repo / "src/wekker/assets/premium_midnight.png"
    logo = repo / "src/wekker/assets/wakesync-logo.png"
    init = repo / "src/wekker/__init__.py"
    for required in (file,entry,artwork,logo,init):
        if not required.is_file():
            print(f"Ontbreekt: {required}",file=sys.stderr)
            return 2
    version_text = init.read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)',version_text)
    version = match.group(1) if match else "onbekend"
    if version != "10.1.1":
        print(
            f"Veiligheidsstop: deze patch is ontwikkeld voor 10.1.1; huidige versie: {version}. "
            "Pas de patch eerst aan op de nieuwe broncode.",
            file=sys.stderr
        )
        return 2

    content=file.read_text(encoding="utf-8")
    if START in content and END in content and NEW.strip() in content:
        print("Premium-UI was al geactiveerd. Geen wijzigingen.")
        return 0
    if START in content or END in content or content.count(OLD)!=1:
        print(
            "Veiligheidsstop: gui/app.py heeft een andere opbouw. "
            "Er is niets overschreven.",
            file=sys.stderr
        )
        return 2
    backup=_backup_path(repo)
    backup.parent.mkdir(parents=True,exist_ok=True)
    if backup.exists() and backup.read_text(encoding="utf-8") != content:
        print(
            f"Veiligheidsstop: bestaande backup wijkt af ({backup}). "
            "Er is niets overschreven.",
            file=sys.stderr
        )
        return 2
    if not backup.exists():
        shutil.copy2(file,backup)
    updated=content.replace(OLD,NEW,1)
    _atomic_write(file,updated.encode("utf-8"))
    print(f"WakeSync Premium geactiveerd (basis v{version}).")
    print(f"Originele gui/app.py is bewaard in: {backup}")
    print("Controleer eerst: python -m compileall -q src tests")
    print("En daarna: python -m pytest -q")
    return 0


def main() -> None:
    parser=argparse.ArgumentParser(description="Activeer WakeSync Premium zonder data te wissen")
    parser.parse_args()
    raise SystemExit(activate())


if __name__=="__main__":
    main()
