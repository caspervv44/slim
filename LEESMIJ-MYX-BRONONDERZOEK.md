# WakeSync 10.2 — MyX-brononderzoek (alleen-lezen)

Deze diagnose controleert waarom er wel lessen zichtbaar zijn in MyX op
13 en 14 oktober 2026, maar WakeSync alleen lessen op 19–23 oktober cachet.

## Installeren
Dit pakket voegt twee bestanden toe en vervangt GEEN bestaande bestanden:

- `tools/diagnose_myx_rooster.py`
- `tests/test_diagnose_myx_rooster.py`

Voeg ze toe aan je lokale GitHub-repository, push en doe op de Pi een `git pull`.

## Uitvoeren op de Raspberry Pi

```bash
cd ~/slim2/slim
source .venv/bin/activate
python3 tools/diagnose_myx_rooster.py --start 2026-10-12 --days 12
```

Het script downloadt de reeds ingestelde MyX-abonnementsfeed in het geheugen
zonder de persoonlijke URL te tonen. Het toont alleen aantallen per kalenderdag.

- **Ruwe starts**: aantal afzonderlijke `VEVENT`-afspraken waarvan DTSTART
  op deze dag valt. Een herhaalde afspraak uit een eerdere week wordt NIET
  als een nieuw bron-event meegeteld.
- **Parser**: aantal lessen dat WakeSync van de ICS maakt voor die datum.
- **Cache**: aantal lessen dat de GUI uit de lokale cache kan laden.
- **RRULE**: terugkerende series (in v10.2 nog niet geëxpandeerd).

## Hoe lees je de resultaten?

- Wel ruwe starts, maar minder bij Parser: parser laat afspraken weg.
- Wel Parser-resultaten, maar minder in Cache: synchronisatie/cacheprobleem.
- Geen ruwe starts voor 13/14, wel veel oude RRULE-series:
  herhalingsexpansie ontbreekt vermoedelijk.
- Geen ruwe starts en geen relevante RRULE-series:
  de *abonnementsfeed* bevat die webapp-lessen niet. Controleer dan
  of MyX hetzelfde rooster exporteert en of een nieuwe feedlink nodig is.

Dit is diagnostiek, geen permanente reparatie. Er worden geen bestanden
verwijderd, gewijzigd of overschreven. Deel de terminaluitvoer (zonder
eigen bewerkingen van de URL). Deel NOOIT de ruwe ICS of de feedlink.

## Lokaal testen

```bash
python3 -m pytest -q tests/test_diagnose_myx_rooster.py
```
