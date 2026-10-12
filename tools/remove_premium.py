#!/usr/bin/env python3
"""Schakel WakeSync Premium uit, zonder alarmen of instellingen te verwijderen."""
from __future__ import annotations

import sys
from pathlib import Path
from apply_premium import _root, _backup_path, _atomic_write, NEW, OLD, START, END


def restore() -> int:
    repo=_root()
    app=repo/"src/wekker/gui/app.py"
    if not app.exists():
        print(f"Bestand ontbreekt: {app}",file=sys.stderr)
        return 2
    current=app.read_text(encoding="utf-8")
    backup=_backup_path(repo)
    if START not in current:
        print("Premium-UI is niet actief. Niets aangepast.")
        return 0
    if current.count(NEW)!=1 or current.count(END)!=1:
        print("Veiligheidsstop: onbekende patchvariant. Niets aangepast.",file=sys.stderr)
        return 2
    original=current.replace(NEW,OLD,1)
    if backup.exists() and backup.read_text(encoding="utf-8")!=original:
        print("Veiligheidsstop: backup en huidige broncode verschillen.",file=sys.stderr)
        return 2
    _atomic_write(app,original.encode("utf-8"))
    print("Oorspronkelijke WakeSync-interface hersteld.")
    print("Alarmen, rooster en instellingen zijn niet gewijzigd.")
    return 0


if __name__ == "__main__":
    raise SystemExit(restore())
