#!/usr/bin/env python3
"""Controleer welke lesdagen WakeSync lokaal uit de MyX-cache kan lezen.

Toont geen feedlink, tokens, lestitels of docentnamen en gaat niet online.
"""
from __future__ import annotations

import argparse
import importlib.util
from datetime import date, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

# Meet EERST welke installatie 'python3 -m wekker' werkelijk gebruikt.
# Anders kan een oude editable install uit ~/slim de nieuwe GUI overrulen.
existing_spec = importlib.util.find_spec("wekker")
installed_origin = (
    Path(existing_spec.origin).resolve()
    if existing_spec is not None and existing_spec.origin
    else None
)
sys.path.insert(0, str(ROOT / "src"))

from wekker.agenda.cache import AgendaCache
from wekker.settings import Settings
from wekker.storage import JsonStore


def main() -> int:
    parser = argparse.ArgumentParser(description="WakeSync agenda-cache diagnosticeren")
    parser.add_argument(
        "--settings", type=Path, default=ROOT / "wekker-settings.json",
        help="Instellingenbestand van de draaiende wekker",
    )
    args = parser.parse_args()
    settings_path = args.settings.expanduser().resolve()
    cache_path = settings_path.with_name(".wakesync-agenda-cache.json")
    print("WakeSync-code:", ROOT)
    print("Python:", sys.executable)
    print("Door python geladen WakeSync:", installed_origin or "niet geïnstalleerd")
    expected_module = (ROOT / "src/wekker/__init__.py").resolve()
    if installed_origin != expected_module:
        print("WAARSCHUWING: Python gebruikt niet deze repo. Herstel met:")
        print(f"  cd {ROOT} && python3 -m pip install -e .")
    print("Instellingen:", settings_path)
    print("Cache:", cache_path)
    print("Agenda-hotfix actief:", (
        "ja" if "# [WakeSync MyX Agenda Hotfix] BEGIN"
        in (ROOT / "src/wekker/gui/app.py").read_text(encoding="utf-8")
        else "nee"
    ))
    if not settings_path.is_file():
        print("FOUT: dit instellingenbestand bestaat niet. Start de GUI met --settings.")
        return 2
    if not cache_path.is_file():
        print("FOUT: cache ontbreekt naast dit instellingenbestand.")
        return 2

    try:
        settings_raw = JsonStore(settings_path).load()
        settings = Settings.from_dict(settings_raw)
        cache = AgendaCache(path=cache_path)
    except Exception as exc:
        print("FOUT bij lezen van instellingen/cache:", type(exc).__name__)
        return 2

    from wekker.clock import SystemClock
    today = SystemClock(settings.locale.timezone).now().date()
    print("Vandaag volgens wekker:", today)
    print("Actieve agendaprovider:", settings.agenda.provider)
    status = cache.status_dict()
    print("Cache-status:", status["status"])
    print("Dagen opgeslagen:", len(status["loaded_days"]))
    volgende = []
    for key in sorted(status["loaded_days"]):
        try:
            dag = date.fromisoformat(key)
            if dag < today or dag > today + timedelta(days=60):
                continue
            aantal = len(cache.get_day(dag))
            if aantal:
                volgende.append((dag, aantal))
        except (ValueError, TypeError, KeyError):
            continue
    print("Lessen vandaag:", len(cache.get_day(today)))
    print("Lesdagen in komende 60 dagen:", len(volgende))
    for dag, aantal in volgende[:20]:
        print(f"  {dag:%Y-%m-%d}: {aantal} les(sen)")
    if not volgende:
        print("Geen toekomstige lessen in de lokale cache. Controleer de ICS-bron.")
        return 1
    if not cache.get_day(today):
        print("Verklaring: vandaag is leeg. Met de hotfix opent Agenda op", volgende[0][0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
