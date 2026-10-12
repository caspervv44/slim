#!/usr/bin/env python3
"""Koppel MyX één keer privé aan deze Raspberry Pi; nooit aan GitHub.

Gebruik: python3 tools/configure_private_myx.py
De persoonlijke webcal-link gaat via getpass naar MyXFeedStore (chmod 0600).
De zichtbare instellingen bevatten alleen de providernaam 'myx'.
"""
from __future__ import annotations

import argparse
import getpass
from pathlib import Path
import sys

# Bij run direct vanuit tools/ is de package toegankelijk zonder pip-installatie.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wekker.agenda.myx_auth import MyXFeedStore, MyXFeedError, normalize_feed_url
from wekker.settings import Settings, default_settings
from wekker.storage import JsonStore


def configure(settings_path: Path, check: bool = False) -> int:
    secret_store = MyXFeedStore()
    if check:
        try:
            secret_present = bool(secret_store.load())
        except MyXFeedError:
            secret_present = False
        print("MyX-feed: privé ingesteld" if secret_present else "MyX-feed: niet ingesteld")
        print("Feedlink en tokens worden nooit getoond.")
        return 0 if secret_present else 1

    # getpass toont het geheime token niet op het scherm of in de shellhistorie.
    print("Plak één keer je persoonlijke MyX webcal://-link.")
    print("Deze wordt uitsluitend lokaal en afgeschermd opgeslagen.")
    try:
        incoming = getpass.getpass("MyX-feedlink (onzichtbare invoer): ")
        normalized = normalize_feed_url(incoming)
    except (EOFError, KeyboardInterrupt):
        print("\nAfgebroken. Geen wijzigingen.")
        return 1
    except MyXFeedError:
        print("Ongeldige MyX-feedlink. Geen wijzigingen.", file=sys.stderr)
        return 2
    finally:
        # Geen feedlink of token loggen.
        try:
            del incoming
        except UnboundLocalError:
            pass

    config = JsonStore(settings_path)
    try:
        saved = config.load()
        # Onleesbare configuratie nooit stilzwijgend door defaults vervangen.
        settings = Settings.from_dict(saved) if saved is not None else default_settings()
        updated = settings.update_from_dict({"agenda": {"provider": "myx"}})
        secret_store.save(normalized)
        # De configuratie bevat uitsluitend de veilige providernaam.
        config.save(updated.to_dict())
    except Exception:
        print("MyX kon niet worden opgeslagen; controleer bestandsrechten.",
              file=sys.stderr)
        return 2

    print("Gelukt: MyX is als agendaprovider ingesteld.")
    print("De persoonlijke link staat lokaal met beperkte bestandsrechten.")
    print("De agendacache wordt gevuld bij de volgende geslaagde synchronisatie.")
    print("Herstart de wekker als de GUI al draaide.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="MyX privé opslaan op deze Raspberry Pi")
    parser.add_argument("--settings", default="wekker-settings.json",
                        help="Pad naar de lokale, niet-gecommitte instellingen")
    parser.add_argument("--check", action="store_true",
                        help="Toon alleen of de privéfeed aanwezig is")
    args = parser.parse_args()
    raise SystemExit(configure(Path(args.settings), check=args.check))


if __name__ == "__main__":
    main()
