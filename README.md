# WakeSync v10.1

WakeSync v10.1 bouwt voort op v10 met het exact aangeleverde C9-logo, datumalarmen, een dragbare klokwijzer met live tijd, smooth toggles, een lichtere Liquid Motion-renderloop, de P-sneltoets voor slaapstand en een nonce-gebaseerde reparatie van de online beheer-tabs.

Belangrijk: de automatische touch-check/touch-reparatie blijft buiten de productsoftware. De fysieke ADS7846/Wayland-touchkwestie wordt afzonderlijk onderzocht.

### MyX live controleren

De gekoppelde feed kan op de Raspberry Pi veilig worden geïnspecteerd zonder dat de geheime feed-URL wordt afgedrukt:

```bash
python -m wekker inspect-myx --days 21
```

Het resultaat meldt onder andere `lessons_with_room`, `room_available` en
`raw_room_hints`. Die laatste sectie laat alleen privacyvriendelijke propertynamen,
aantallen en gevonden lokaalcodes zien; de geheime feed-URL wordt niet afgedrukt.
Als de bron geen lokaal levert, verbergt WakeSync het lokaalveld volledig in
plaats van een streepje te tonen.


WakeSync is een Raspberry Pi 5-schoolwekker met een 5-inch 800×480-interface,
MyX/iCalendar-rooster, online beheer via `veendomain.nl` en een veilige
software-updater.

## Wat v10.1 verandert

- Het officiële logo gebruikt exact de aangeleverde vorm; thema's passen hun omgeving aan in plaats van de logokleuren te wijzigen.
- Een nieuw alarm kan eerst een datum of **Dagelijks** kiezen en daarna uur/minuten.
- De klokwijzer volgt dragbewegingen en de digitale tijd erboven loopt live mee.
- Alarm-/speaker-/lamp-schakelaars gebruiken smooth touchvriendelijke toggles.
- `P` zet de GUI direct in slaapstand voor demonstraties.
- Liquid Motion gebruikt minder splinepunten/lagen en blijft bij een renderfout uit de weg van de Tk-eventloop.
- `test2.pl` gebruikt een CSP-nonce voor de tab-JavaScript; zonder JavaScript blijven de beheerpanelen als fallback zichtbaar.
- Het primaire webalarm ondersteunt optioneel een ISO-datum (`YYYY-MM-DD`).

## Wat v10 verandert

- Het goedgekeurde **C9-logo** is de vaste WakeSync-branding in de GUI,
  opstartweergave, slaapmodus en online beheer.
- De automatische touch-displaycheck is uit de product-GUI en diagnose
  verwijderd. De huidige ADS7846-touchbediening werkt op de echte testopstelling
  nog niet betrouwbaar en wordt daarom niet als werkend gepresenteerd.
- De hoofdnavigatie heeft nu vier vaste tabs:
  **Vandaag · Agenda · Alarm · Instellingen**.
- Het nieuwe **Alarm**-scherm ondersteunt meerdere alarmen. Links staat een **+**;
  daarna kiest de gebruiker eerst het uur en daarna de minuten op een 360°-dial.
  Pas na selectie van een bestaand alarm verschijnt rechts de configuratie voor
  snooze, volume, speaker en lamp.
- De agenda toont maximaal zes lessen per pagina. Daardoor blijft een normale
  volledige schooldag, inclusief een laatste les van 15:30–17:00, zichtbaar
  zonder dat die ongemerkt op een tweede pagina verdwijnt.
- De MyX/Xedule-lokaalparser behandelt `LOCATION:-` en `LOCATION:—` als
  lege placeholders en zoekt daarna verder in `DESCRIPTION`, `X-ALT-DESC`,
  `COMMENT`, `RESOURCES` en vendorvelden.
- De slaapmodus heeft instelbare professionele effecten:
  **uit**, **zachte gloed**, **pulserende gloed**, **aurora** en
  **Liquid Motion**.
  De gloedsterkte is instelbaar van 0–100%.
- `test2.pl` heeft een responsieve beheerinterface:
  op desktop een vaste zijbalk, op telefoon horizontale tabnavigatie.
  De hoofdonderdelen zijn Alarm, Weergave, Rooster en Systeem.
- WakeSync gebruikt voor de klok altijd de lokale Raspberry Pi-systeemtijd en
  ingestelde tijdzone. Een internetverbinding is niet nodig om de tijd tijdens
  normaal bedrijf te laten doorlopen.
- De v8-updater, rollback, persistente alarmstatus, agenda-cache en cloudrevision
  blijven behouden.

## Belangrijk over tijd zonder internet

WakeSync haalt de actuele kloktijd niet uit de cloud. De GUI gebruikt direct de
Raspberry Pi-systeemklok via de ingestelde `zoneinfo`-tijdzone. Als wifi
wegvalt, blijven tijd, alarm en lokaal opgeslagen agenda dus werken.

Dit is iets anders dan tijd bewaren wanneer de Pi volledig spanningsloos is.
Daarvoor is de Raspberry Pi 5-RTC en, indien tijdbehoud tijdens volledige
stroomuitval nodig is, een passende RTC-batterij/configuratie bepalend.

## Installatie / upgrade

```bash
cd ~/slim
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
python -m wekker healthcheck
python -m wekker gui
```

De product-GUI gebruikt geen lokale webapp op poort 8080. Online beheer loopt
via:

`https://veendomain.nl/klok/test2.pl`

Plaats voor v10.1 ook `deploy/cloud/test2.pl` op de WAMP-server. De health-URL:

`https://veendomain.nl/klok/test2.pl?health=1`

moet `service: "wakesync"`, `version: 10` en `release: "10.1.0"` melden.

## Online beheer

De beheerpagina is responsive:

- **desktop:** zijbalk met tabbladen;
- **telefoon:** horizontaal scrollbare tabbladen;
- **Alarm:** alarmtijd, snooze, volume en geplande lamp/speakeropties;
- **Weergave:** thema, tijdzone, tijdsnotatie, slaapmodus en gloed;
- **Rooster:** provider, synchronisatie en MyX/iCalendar-feed;
- **Systeem:** status, beveiliging en wachtwoordbeheer.

Openbare uitleg op de loginpagina beschrijft welke onderdelen configureerbaar
zijn zonder privé-instellingen van een wekker prijs te geven.

## Agenda en lokalen

De parser ondersteunt onder andere deze Xedule-vormen:

```text
LOCATION:-
DESCRIPTION:... LVM-E2.12 / E2.14 - LVM ...
```

en:

```text
LOCATION:—
X-ALT-DESC;FMTTYPE=text/html:<div>... LVM E3.07 - LVM ...</div>
```

Als de echte feed geen lokaalveld bevat, verbergt WakeSync het lokaalblok
volledig in plaats van `Lokaal: -` te tonen. Controleer een gekoppelde feed
veilig met `python -m wekker inspect-myx --days 21`.

In beide gevallen wordt het lokaal uit de beschrijving gehaald en doorgegeven
aan zowel **Vandaag** als **Agenda**.

## Touchscreen

WakeSync v10.1 voert geen automatische touchcheck of automatische touchreparatie
meer uit in de productsoftware. De ADS7846-controller kan door Linux zichtbaar
zijn terwijl de grafische bediening nog niet werkt. Dit hardware/Wayland-
probleem wordt apart onderzocht zodat de app geen misleidende status toont.

Er is geen touch-check meer beschikbaar via de product-GUI of product-CLI. De bestaande helpercode wordt alleen intern bewaard voor later handmatig onderzoek.

## Updater

**Instellingen → Software** installeert standaard alleen een gepubliceerde,
niet-prerelease GitHub Release uit `caspervv44/slim`.

De updater:

1. downloadt de release via HTTPS;
2. controleert versie en optioneel SHA-256;
3. maakt een back-up;
4. houdt een operatiejournal bij;
5. installeert de nieuwe broncode;
6. voert `python -m wekker healthcheck` uit;
7. start pas na succesvolle controle opnieuw;
8. rolt bij fouten terug naar de vorige broncode.

De app-updater flasht geen Raspberry Pi OS, kernel of EEPROM.

## Lokale bestanden

Naast `wekker-settings.json` kan WakeSync onder andere gebruiken:

- `.wekker-cloud.json` — apparaatidentiteit en cloudrevision;
- `.wakesync-agenda-cache.json` — laatste bekende agenda;
- `.wakesync-alarm.json` — alarm/snooze/dismissstatus;
- `wakesync-update.log` — updaterlog;
- `.wakesync-update-status.json` — laatste updaterstatus.

Zet deze runtimebestanden niet in een publieke repository.

## Testen

```bash
python -m compileall -q src tests
python -m pytest -q
perl -c deploy/cloud/test2.pl
```

De v10.1-regressietests dekken onder andere:

- een dag met vijf lessen waarbij 15:30–17:00 zichtbaar moet blijven;
- `LOCATION:-`/`—` met lokaal in Xedule-beschrijving;
- lokaal van ICS-parser tot Vandaag én Agenda;
- 360° alarmkiezer;
- slaapgloedinstellingen;
- offline gebruik van de lokale systeemklok;
- cloudbeveiliging en updater/rollback uit v8.
