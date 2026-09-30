# WakeSync v8

WakeSync is een Raspberry Pi 5-schoolwekker voor een 5-inch touchscreen. De
app combineert een fysieke wekkerinterface, MyX/iCalendar-rooster, online
beheer via `veendomain.nl` en een veilige software-updater.

## Wat v8 verandert

V8 voert de goedgekeurde eerste bouwscope uit: **A1–A7 + B1–B6**, aangevuld
met de beperkte diagnose uit C4.

- Waveshare 5-inch/ADS7846-profiel met detectie, backup, labwc-outputmapping
  en controle na herstart.
- Updater met stabiele GitHub Releases, operatiejournal, rollback en
  app-healthcheck vóór acceptatie.
- Online beheer (`test2.pl`) toont na een anonieme POST geen instellingen.
- Agenda-HTTP en MyX-feedverwerking draaien buiten de alarm-/GUI-thread.
- Rooster én runtime-alarmstatus worden lokaal persistent opgeslagen.
- Snooze/dismiss blijven correct na een herstart; een gemist alarm wordt
  alleen binnen 10 minuten hersteld en anders als melding getoond.
- Instellingen worden eerst atomair opgeslagen en daarna live toegepast.
- Alarmtransities committen pas na succesvolle hardwareactie.
- Hoofdscherm toont huidige/volgende les met een vaste, grote lokaalweergave.
- De volledige dagagenda is bereikbaar via paginering; 6–12 lessen worden
  niet meer afgekapt.
- Apart alarm-/snoozescherm met grote snoozeknop; stoppen blijft via de
  fysieke productknop.
- Eerlijke roosterstatus: `Nog niet geladen`, `Bijgewerkt om …` of
  `Eerder rooster getoond`.
- Instellingen zijn verdeeld in Weergave, Online beheer, Software,
  Touchscreen & beeld en Diagnose.
- Diagnose toont versie, syncstatus, NTP, display/touch en backlightstatus
  zonder device-key, wachtwoord of geheime MyX-feed te exporteren.

C1 (school/vakantieprofielen), C2 (wekken vanaf eerste les), echte
speaker/lampdrivers en proces/watchdog-herstel zijn bewust nog niet onderdeel
van deze versie.

## Installatie / upgrade vanaf v7

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

Plaats voor v8 ook `deploy/cloud/test2.pl` op de WAMP-server. De health-URL:

`https://veendomain.nl/klok/test2.pl?health=1`

moet `service: "wakesync"` en `version: 8` melden.

## Touchscreen

Bekend profiel:

- Waveshare 5-inch HDMI LCD
- 800×480
- ADS7846 Touchscreen
- Raspberry Pi OS Wayland/labwc
- verwachte actieve Wayland-output: `HDMI-A-1`

Status bekijken:

```bash
python -m wekker touch-setup --status
```

Als ADS7846 al door Linux wordt gezien, corrigeert WakeSync alleen de
gebruikersmapping in `~/.config/labwc/rc.xml` en laat bootconfig met rust.

Op een schone installatie waar ADS7846 nog niet wordt gezien, moet het profiel
expliciet worden bevestigd:

```bash
sudo .venv/bin/python -m wekker touch-setup \
  --profile waveshare-5-hdmi-ads7846 \
  --confirmed \
  --home "$HOME"
sudo reboot
```

Na de reboot:

```bash
python -m wekker touch-setup --verify
```

**Belangrijk:** de boot-overlay is alleen voor dit bevestigde hardwareprofiel.
Gebruik hem niet voor een ander Waveshare-model.

## Updater

De GUI-pagina **Instellingen → Software** installeert standaard alleen een
gepubliceerde, niet-prerelease GitHub Release uit `caspervv44/slim`.

Een bewegende `main`/`master`-branch wordt niet stil als productie-update
gebruikt. Alleen voor ontwikkeling kan dit expliciet:

```bash
export WAKESYNC_UPDATE_ALLOW_BRANCH=1
```

De updater:

1. downloadt en valideert het ZIP-archief;
2. controleert de projectversie en optioneel SHA-256;
3. maakt een volledige backup van de te vervangen broncode;
4. journaled iedere target vóór de eerste wijziging;
5. installeert de nieuwe versie;
6. voert `python -m wekker healthcheck` uit;
7. start WakeSync pas daarna opnieuw;
8. rolt bij een fout de aangeraakte targets terug.

Lokale settings, cloudidentiteit, MyX-authdata, agenda-cache, alarmstatus,
`.git` en `.venv` vallen buiten de vervangtargets.

## Lokale bestanden

Naast `wekker-settings.json` kan WakeSync o.a. deze sidecars gebruiken:

- `.wekker-cloud.json` — apparaatidentiteit en cloudrevision;
- `.wakesync-agenda-cache.json` — laatste bekende rooster;
- `.wakesync-alarm.json` — snooze/dismiss/triggerstatus;
- `wakesync-update.log` — updaterlog;
- `.wakesync-update-status.json` — laatste updaterstatus.

Deze bestanden mogen niet in een publieke repository terechtkomen.

## Testen

```bash
python -m compileall -q src tests
python -m pytest -q
perl -c deploy/cloud/test2.pl
```

De v8-tests dekken onder andere blokkend netwerkwerk, persistente
alarm/agenda-status, driverfouten, touchmapping, 12-lessenpaginering,
anonieme CGI-POSTs en rollbackfouten in alle updaterfasen.

## Hardwarestatus

De huidige bekende displayopstelling heeft geen entry onder
`/sys/class/backlight` en meldt via `ddcutil` dat DDC/CI niet wordt
ondersteund. Daarom presenteert WakeSync de donkere slaapweergave niet als
echte hardware-backlightregeling. Zie `docs/hardware-inventory.md`.
