#!/usr/bin/env python3
"""Onderzoek waarom MyX-lessen ontbreken zonder privégegevens af te drukken.

Dit script is alleen-lezen: het gebruikt de lokaal opgeslagen feedlink,
downloadt de iCalendar-feed in het geheugen en vergelijkt drie stappen:
bronafspraken, verwerkte lessen en cache. Het wijzigt niets.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wekker.agenda.cache import AgendaCache
from wekker.agenda.myx import (
    MyXAgendaProvider,
    MyXConfig,
    _parse_datetime,
    _split_property,
    _unfold_ics,
    parse_ics,
)
from wekker.agenda.myx_auth import MyXFeedStore


@dataclass
class BronAnalyse:
    evenementen: int
    startdatums: Counter
    herhalingen: int
    oude_herhalingen: int
    uitzonderingen: int
    extra_datums: int
    geannuleerd: int
    hele_dagen: int
    onleesbare_starts: int


def analyseer_bron(ics: str, start_datum: date) -> BronAnalyse:
    """Tel alleen eigenschappen en lokale datums; geen vaknamen of deelnemers."""
    aantal = 0
    startdatums: Counter = Counter()
    herhalingen = 0
    oude_herhalingen = 0
    uitzonderingen = 0
    extra_datums = 0
    geannuleerd = 0
    hele_dagen = 0
    onleesbare_starts = 0

    in_event = False
    event_start: date | None = None
    heeft_herhaling = False
    event_hele_dag = False

    def voltooi_event() -> None:
        nonlocal aantal, herhalingen, oude_herhalingen, hele_dagen
        aantal += 1
        if event_start is not None:
            startdatums[event_start] += 1
        if heeft_herhaling:
            herhalingen += 1
            if event_start is not None and event_start < start_datum:
                oude_herhalingen += 1
        if event_hele_dag:
            hele_dagen += 1

    for raw_line in _unfold_ics(ics):
        line = raw_line.lstrip("\ufeff")
        markering = line.strip().upper()
        if markering == "BEGIN:VEVENT":
            in_event = True
            event_start = None
            heeft_herhaling = False
            event_hele_dag = False
            continue
        if markering == "END:VEVENT":
            if in_event:
                voltooi_event()
            in_event = False
            continue
        if not in_event or not line or ":" not in line:
            continue

        try:
            naam, params, waarde = _split_property(line)
        except Exception:
            continue
        if naam == "DTSTART":
            try:
                dt = _parse_datetime(waarde, params)
                if dt is None:
                    event_hele_dag = True
                else:
                    event_start = dt.date()
            except Exception:
                onleesbare_starts += 1
        elif naam == "RRULE":
            heeft_herhaling = True
        elif naam == "RECURRENCE-ID":
            uitzonderingen += 1
        elif naam == "RDATE":
            extra_datums += 1
        elif naam == "STATUS" and waarde.strip().upper() == "CANCELLED":
            geannuleerd += 1

    return BronAnalyse(
        aantal, startdatums, herhalingen, oude_herhalingen,
        uitzonderingen, extra_datums, geannuleerd, hele_dagen,
        onleesbare_starts,
    )


def oordeel(bron: BronAnalyse, parsed: Counter, cache: Counter, start: date, dagen: int) -> str:
    """Geef aan in welke verwerkingsstap lessen verdwijnen."""
    periode = [start + timedelta(days=offset) for offset in range(dagen)]
    ontbrekend = [
        dag for dag in periode
        if bron.startdatums[dag] > 0 and parsed[dag] < bron.startdatums[dag]
    ]
    cache_achter = [
        dag for dag in periode
        if parsed[dag] > 0 and cache[dag] < parsed[dag]
    ]
    if ontbrekend:
        return (
            "PARSER: de ruwe feed heeft afspraken die als losse lessen niet volledig "
            "door de parser terugkomen. Onderzoek status/hele-dag/afwijkende velden."
        )
    if cache_achter:
        return (
            "CACHE: de parser ziet meer lessen dan de cache bewaart. "
            "Controleer de synchronisatiestap en het instellingenpad."
        )
    zichtbaar = sum(bron.startdatums[d] for d in periode)
    if bron.oude_herhalingen:
        return (
            "HERHALINGEN: de feed bevat terugkerende afspraken waarvan de "
            "begindatum voor dit bereik valt. WakeSync 10.2 verwerkt RRULE "
            "momenteel niet tot afzonderlijke lesdagen. Dit kan lessen verklaren."
        )
    if zichtbaar == 0:
        return (
            "BRON: de ruwe MyX-feed bevat geen zelfstandige afspraken in dit "
            "datumbereik. De website en de abonnementsfeed kunnen verschillen. "
            "Controleer of het abonnement hetzelfde rooster exporteert."
        )
    return (
        "BRON/PARSER/CACHE komen voor de getoonde beginmomenten overeen. "
        "Als de website meer lessen toont, levert de abonnementsfeed die "
        "blijkbaar niet als afzonderlijke afspraken aan."
    )


def onderzoek(settings_path: Path, start: date, dagen: int, *,
              feed_store: MyXFeedStore | None = None,
              provider_type=MyXAgendaProvider) -> int:
    """Print een privacyvriendelijke diagnose; wijzig nooit instellingen of cache."""
    geheim = (feed_store or MyXFeedStore()).load()
    if not geheim:
        print("Geen privé-MyX-feed opgeslagen onder deze Linux-gebruiker.")
        return 2

    provider = provider_type(MyXConfig(feed_url=geheim))
    # De volledige feed-URL blijft uitsluitend in het geheugen; nooit afdrukken.
    ics = provider.fetch_raw_ics(start, start + timedelta(days=dagen))
    del geheim
    bron = analyseer_bron(ics, start)
    try:
        lessen = parse_ics(ics)
    except Exception as exc:
        print("De iCalendar-parser gaf een fout van type:", type(exc).__name__)
        print("Geen privégegevens afgedrukt. Deel uitsluitend deze foutsoort.")
        return 3

    parsed = Counter(les.start.date() for les in lessen)
    cache_path = settings_path.with_name(".wakesync-agenda-cache.json")
    cache = AgendaCache(path=cache_path)
    cache_tellingen = Counter({
        start + timedelta(days=offset): len(cache.get_day(start + timedelta(days=offset)))
        for offset in range(dagen)
    })
    del ics

    print("WakeSync MyX-brononderzoek (alleen-lezen)")
    print("Cache aanwezig:", "ja" if cache_path.is_file() else "nee")
    print("VEVENT-blokken in feed:", bron.evenementen)
    print("RRULE-herhalingen:", bron.herhalingen)
    print("RRULE's met begindatum voor dit bereik:", bron.oude_herhalingen)
    print("RECURRENCE-ID-uitzonderingen:", bron.uitzonderingen)
    print("RDATE-regels:", bron.extra_datums)
    print("STATUS:CANCELLED:", bron.geannuleerd)
    print("Hele-dag-gebeurtenissen:", bron.hele_dagen)
    print("Niet-herkende DTSTART:", bron.onleesbare_starts)
    print()
    print("Datum        Ruwe starts   Parser   Cache")
    print("------------------------------------------")
    for offset in range(dagen):
        dag = start + timedelta(days=offset)
        print(
            f"{dag.isoformat()}    {bron.startdatums[dag]:>5}"
            f"       {parsed[dag]:>5}   {cache_tellingen[dag]:>5}"
        )
    print()
    print("Voorlopige conclusie:", oordeel(bron, parsed, cache_tellingen, start, dagen))
    print("De feedlink, lestitels, docenten en lokalen zijn NIET afgedrukt.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--settings", type=Path, default=ROOT / "wekker-settings.json",
        help="Bestand met de lokale WakeSync-instellingen.",
    )
    parser.add_argument(
        "--start", type=date.fromisoformat, default=date.today(),
        help="Begindatum (YYYY-MM-DD); standaard vandaag.",
    )
    parser.add_argument("--days", type=int, default=14, help="Aantal dagen (1..60).")
    args = parser.parse_args()
    if not 1 <= args.days <= 60:
        parser.error("--days moet tussen 1 en 60 liggen")
    try:
        return onderzoek(args.settings.resolve(), args.start, args.days)
    except Exception as exc:
        # URL's en ICS-inhoud komen bewust niet in de terminal terecht.
        print("Onderzoek niet gelukt; fouttype:", type(exc).__name__, file=sys.stderr)
        print("De opgeslagen MyX-koppeling is niet aangepast.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
