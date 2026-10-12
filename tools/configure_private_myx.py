#!/usr/bin/env python3
"""Veilig MyX instellen, de echte ICS ophalen en de WakeSync-cache bijwerken.

Werkt vanuit de bestaande slim-map. De feedlink blijft uitsluitend in
MyXFeedStore (~/.local/share/aventus-wekker, normaal rechten 0600).

Voor bestaande koppelingen:
    python3 tools/configure_private_myx.py --refresh
    python3 tools/configure_private_myx.py --check

Zonder opties kun je een feed voor het eerst invoeren; daarna synchroniseert
het script direct. Gebruik --settings als de wekker met een ander bestand start.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
import getpass
import logging
import os
from pathlib import Path
import re
import sys

# Gebruik precies de code uit déze repository, ook als elders een andere
# WakeSync-versie is geïnstalleerd.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wekker.agenda.myx_auth import MyXFeedStore, MyXFeedError, normalize_feed_url
from wekker.settings import Settings, SettingsError, default_settings
from wekker.storage import JsonStore, StorageError

# Geen algemene debuglogs tijdens een privé-ICS-synchronisatie.
logging.basicConfig(level=logging.ERROR, format="%(levelname)s: %(message)s")


def _public_error(message: object) -> str:
    """Verberg URL's en tokens voordat een fout op de terminal verschijnt."""
    clean = str(message or "Onbekende fout")
    clean = re.sub(r"(?:webcal|https?)://[^\s\"'<>]+", "[privélink verborgen]", clean, flags=re.I)
    clean = re.sub(r"(?i)\b(?:bearer|token|authorization)\s*[:= ]+\S+", "[privégegeven verborgen]", clean)
    # Een fout kan UUID's uit de tokenachtige feedpath noemen. Toon deze nooit.
    clean = re.sub(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        "[id verborgen]", clean, flags=re.I,
    )
    return clean[:250]


def _load_settings_file(path: Path) -> tuple[JsonStore, Settings]:
    store = JsonStore(path)
    raw = store.load()
    # Let op: kapotte instellingen NOOIT stilzwijgend wissen of resetten.
    settings = Settings.from_dict(raw) if raw is not None else default_settings()
    return store, settings


def _ensure_provider(path: Path) -> bool:
    """Schakel uitsluitend agenda.provider + eventueel auto-sync in."""
    if not path.is_file():
        raise StorageError(
            "Instellingenbestand bestaat niet. Geef met --settings het pad op "
            "dat de draaiende WakeSync-GUI gebruikt."
        )
    store, current = _load_settings_file(path)
    patch: dict[str, object] = {}
    if current.agenda.provider != "myx":
        patch["provider"] = "myx"
    if current.agenda.auto_sync_minutes == 0:
        patch["auto_sync_minutes"] = 15
    if not patch:
        return False
    updated = current.update_from_dict({"agenda": patch})
    store.save(updated.to_dict())
    if "auto_sync_minutes" in patch:
        print("Automatische agendasynchronisatie aangezet: iedere 15 minuten.")
    if "provider" in patch:
        print("Agendaprovider ingesteld op MyX.")
    return True


def _load_secret() -> bool:
    try:
        # De returnwaarde wordt bewust niet opgeslagen of geprint.
        return bool(MyXFeedStore().load())
    except MyXFeedError:
        return False


def _status(path: Path) -> int:
    print("Instellingen:", path)
    print("Cache:", path.with_name(".wakesync-agenda-cache.json"))
    print("Linux-gebruiker:", getpass.getuser())
    print("Persoonlijke MyX-feed:", "opgeslagen" if _load_secret() else "ontbreekt/onleesbaar")
    try:
        store, settings = _load_settings_file(path)
        print("Actieve agendaprovider:", settings.agenda.provider)
        print("Automatische sync (minuten):", settings.agenda.auto_sync_minutes)
        from wekker.agenda.cache import AgendaCache
        cache = AgendaCache(path=path.with_name(".wakesync-agenda-cache.json"))
        status = cache.status_dict()
        print("Laatste cachesynchronisatie:", status["status"])
        print("Dagen in cache:", len(status["loaded_days"]))
        if status.get("last_success"):
            print("Laatste geslaagde sync:", status["last_success"])
        if status["status"] == "error":
            print("Laatste cachefout:", _public_error(status.get("error")))
        ready = settings.agenda.provider == "myx" and _load_secret()
        if not ready:
            print("ACTIE: voer --refresh uit om de MyX-koppeling te herstellen.")
        elif status["status"] != "ok":
            print("ACTIE: voer --refresh uit om de cache daadwerkelijk te vullen.")
        return 0 if ready else 2
    except (StorageError, SettingsError, OSError, ValueError) as exc:
        print("Instellingen controleren mislukt:", _public_error(exc), file=sys.stderr)
        return 2


def _sync(path: Path) -> int:
    """Synchroniseer nu meteen; geen wachten op een achtergrondinterval."""
    print("Instellingen:", path)
    print("Cache:", path.with_name(".wakesync-agenda-cache.json"))
    print("Linux-gebruiker:", getpass.getuser())
    if not _load_secret():
        print(
            "Geen bruikbare MyX-feed opgeslagen onder deze Linux-gebruiker. "
            "Voer het script zonder --refresh uit om hem privé in te voeren.",
            file=sys.stderr,
        )
        return 2
    try:
        _ensure_provider(path)
    except (StorageError, SettingsError, OSError, ValueError) as exc:
        print("Instellingen niet gewijzigd:", _public_error(exc), file=sys.stderr)
        return 2

    runtime = None
    try:
        from wekker.main import build_default, shutdown
        runtime = build_default(str(path), enable_cloud=False)
        if runtime.ctx.settings.agenda.provider != "myx":
            print("MyX werd niet als provider geladen; controleer --settings.", file=sys.stderr)
            return 2

        # MyXAuthManager in de app en dit script moeten dezelfde privéfeed zien.
        if not runtime.ctx.myx_auth.status().get("feed_configured"):
            print(
                "De GUI-code vindt geen privéfeed voor deze Linux-gebruiker. "
                "Controleer onder welke gebruiker WakeSync draait.",
                file=sys.stderr,
            )
            return 2

        print("MyX downloaden en cache vullen (maximaal circa 15 seconden)...")
        gelukt = bool(runtime.ctx.sync.sync_default_window())
        cache = runtime.ctx.cache
        meta = cache.status_dict()
        if not gelukt:
            print("Synchronisatie mislukt:", _public_error(meta.get("error")), file=sys.stderr)
            print("De bestaande agendagegevens zijn niet gewist.", file=sys.stderr)
            return 1

        now = runtime.ctx.clock.now()
        horizon = min(max(int(getattr(getattr(runtime.ctx.sync, "_provider", None), "sync_horizon_days", 21)), 1), 60)
        totaal = sum(
            len(cache.get_day(now.date() + timedelta(days=offset)))
            for offset in range(horizon)
        )
        vandaag = len(cache.get_day(now.date()))
        print("Synchronisatie: GELUKT")
        print("Cache-bestand:", path.with_name(".wakesync-agenda-cache.json"))
        print("Gevulde kalenderdagen:", len(meta["loaded_days"]))
        print("Lessen vandaag:", vandaag)
        print(f"Lessen komende {horizon} dagen:", totaal)
        if totaal == 0:
            print(
                "Let op: de feed was bereikbaar, maar leverde geen lessen "
                "voor deze periode. Controleer MyX en je roosterperiode."
            )
        print("Sluit de lopende WakeSync-GUI volledig af en start opnieuw.")
        return 0
    except Exception as exc:
        # Nooit een traceback met een eventuele URL/token printen.
        print("Synchronisatie kon niet starten:", _public_error(exc), file=sys.stderr)
        return 2
    finally:
        if runtime is not None:
            try:
                shutdown(runtime)
            except Exception:
                pass


def configure(settings_path: Path, check: bool = False, refresh: bool = False) -> int:
    path = settings_path.expanduser().resolve()
    if check:
        return _status(path)
    if refresh:
        return _sync(path)

    print("Plak één keer je persoonlijke MyX webcal://-link.")
    print("Deze wordt uitsluitend lokaal opgeslagen; de link verschijnt niet op het scherm.")
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
        try:
            del incoming
        except UnboundLocalError:
            pass

    try:
        # Eerst instellingen valideren, zodat corrupte JSON niet wordt overschreven.
        _load_settings_file(path)
        MyXFeedStore().save(normalized)
        del normalized
        _ensure_provider(path)
    except (StorageError, SettingsError, MyXFeedError, OSError, ValueError) as exc:
        print("Koppeling niet volledig opgeslagen:", _public_error(exc), file=sys.stderr)
        return 2

    print("MyX-link veilig opgeslagen. We synchroniseren nu ook direct.")
    return _sync(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="MyX-feed koppelen, synchroniseren en controleren")
    parser.add_argument(
        "--settings",
        type=Path,
        default=ROOT / "wekker-settings.json",
        help="Exact hetzelfde JSON-instellingenbestand als de draaiende GUI gebruikt",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="Controleer opslag/cache, zonder netwerk")
    group.add_argument("--refresh", action="store_true", help="Synchroniseer met bestaande opgeslagen feed")
    args = parser.parse_args()
    raise SystemExit(configure(args.settings, check=args.check, refresh=args.refresh))


if __name__ == "__main__":
    main()
