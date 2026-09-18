# Aventus Wekker — eerste prototype (v0.2)

Slimme wekker in Python die **zonder Raspberry Pi** op een Windows-laptop
ontwikkeld en getest kan worden. Hardware zit achter interfaces; op de laptop
draaien mocks, op de Pi komen later echte drivers zonder de core te herschrijven.

## Eerste prototype

```text
Display + speaker + lamp + één button + Raspberry Pi 5
```

## Uitgesteld naar een latere fase

```text
Wielen
Motoren
Motorcontroller
Touchdisplay / touchsensoren
Extra buttons
Geavanceerde beweging
```

Bewegingshardware is uitgesteld naar een latere prototypefase en maakt geen
deel uit van de eerste werkende versie. De algemene hardware-Protocols
(`MotorController`, `TouchSensor`) blijven behouden voor later, maar het
prototype start en werkt volledig zonder.

## Wat is gebouwd

- **Wekker-core** (`src/wekker/alarm/core.py`): expliciete state machine
  `SLEEPING → RINGING → DISMISSED`, met optionele snooze
  (`RINGING → SNOOZED → RINGING`). Speaker en lamp bij alarm zijn afzonderlijk
  in/uitschakelbaar via instellingen.
- **Button-controller** (`src/wekker/button/controller.py`): één fysieke button
  met debounce (0,3 s). Bij actief alarm handelt een druk het alarm af; zonder
  alarm gaat de lamp tijdelijk aan (instelbaar, default 30 s, timer reset bij
  nieuwe druk, automatisch uit, veilig uit bij shutdown).
- **Hardware abstraction** (`src/wekker/hardware/`): Protocols voor
  display/speaker/lamp/button (+ bewaarde motor/touch-protocols voor later)
  en `mock.py` met toestand-bijhouding en event-simulatie (`press()`).
- **Displaymanager** (`src/wekker/display/manager.py`): tijd, volgend alarm,
  alarmstatus (`ALARM!`), lessen/docent/lokaal en korte meldingen (bv. lamp),
  met auto-uit en nachtmodus (`off`/`dim`).
- **Agenda** (`src/wekker/agenda/`): intern model (`Lesson` met `source`),
  `AgendaProvider`-protocol + register (alleen `mock` werkt; Magister,
  Somtoday, Osiris en MyX zijn kiesbaar maar melden eerlijk
  "nog niet beschikbaar"), `AgendaCache` met stale-detectie en fouttolerante
  `AgendaSyncService`. Periodieke auto-sync volgens instelling.
- **Instellingen + opslag**: gevalideerde dataclasses (`alarm`, `lamp`,
  `display`, `agenda`), atomair JSON-schrijven met fsync, terugval op defaults
  bij corrupte opslag. Geen wachtwoorden/tokens; logs worden geredigeerd.
- **Setup-API** (`src/wekker/api/server.py`): stdlib-HTTP (geen Flask nodig),
  prototype-endpoints (status, settings, agenda-items, lamp, speaker-test,
  alarm-dismiss, button-press) + mobiele setup-pagina op `/`.
  De wekker blijft zelfstandig werken zonder telefoon.
- **Tests**: unit + integratie (zie onder). Architectuur: `docs/architecture.md`.

## Vereisten

- Python 3.11+ (ontwikkeld/getest op 3.12, Windows)
- Alleen dev-dependency: `pytest`

## Lokaal starten

```powershell
cd wekker
pip install -e ".[dev]"
python -m wekker --port 8080
# open http://127.0.0.1:8080 voor de mobiele setup-pagina
```

Instellingen worden bewaard in `wekker-settings.json` (naast de startmap).

## Simulatie (zonder Raspberry Pi)

De simulatie gebruikt de echte wekker-core, button-controller, instellingen en
agenda-services met een bestuurbare klok en mock-hardware. Er is geen tweede
wekkerlogica.

```powershell
python -m wekker simulate                    # interactief (typ 'help')
python -m wekker simulate --demo             # alarmcyclus + lamptimer in één keer
python -m wekker simulate --commands "advance 10;button;status"
python -m wekker simulate --start 07:29:50 --alarm 07:30 --snooze 5 --lampdur 30
```

Commando's: `status`, `display`, `advance <sec>`, `snooze`, `button`,
`dismiss`, `trigger`, `lamp on|off`, `sync`, `alarm <HH:MM>`,
`snoozemin <n>`, `lampdur <n>`, `log [n]`, `demo`, `help`, `quit`.

Voorbeeldcyclus: `advance 10` (alarm gaat af, display toont `ALARM!`) →
`button` (alarm afgehandeld) → `button` (lamp 30 s aan) → `advance 30`
(lamp automatisch uit).

Wat simulatie wel/niet bewijst:

- Wel: toestandslogica, snooze-timing, button-debounce, lamptimer,
  displayinhoud, agendaweergave, instellingen en foutafhandeling.
- Niet: echte GPIO-timing en debouncing op hardware, LED-helderheid,
  geluidskwaliteit, stroomgedrag en Wi-Fi — daarvoor blijft de Pi nodig.

## Setup-app (telefoon)

Open `http://<pi-adres>:8080/` op de telefoon (lokaal: `http://127.0.0.1:8080/`).
De pagina is mobielvriendelijk en kan: verbinding testen, status/tijd/volgend
alarm bekijken, lamp aan/uit/testen, speaker testen, alarm afhandelen, button
simuleren, instellingen bekijken/wijzigen, agenda-provider kiezen en
mock-agendagegevens (met "gesimuleerd"-badge) bekijken. Lokaal prototype
zonder inlog; niet zonder meer op een open netwerk zetten.

## Tests draaien

```powershell
pip install -e ".[dev]"
python -m pytest -q
```

Verwachting: alle tests groen. Daarnaast:

```powershell
python -m compileall -q src tests
```

## Wat nog mock is

Display, speaker, lamp en button (`src/wekker/hardware/mock.py`). GPIO-pinnen
liggen nergens vast; echte drivers worden pas geschreven als de onderdelen
fysiek zijn gecontroleerd. De agenda-provider is een mock; er zijn **geen
echte Magister/Osiris/MyX/Somtoday-koppelingen** — eerst per platform
onderzoeken wat officieel kan (zie `docs/architecture.md`).

## Wat morgen op de Raspberry Pi moet gebeuren

Zie `docs/hardware-inventory.md` (wat is bekend/onbekend) en
`docs/hardware-integration-plan.md` (aanpak, libraries, testfases, veiligheid).

1. Onderdelen fysiek controleren (displaytype, speaker, lamp-stroomopname,
   button-bedrading) en inventarisatie aanvullen.
2. `src/wekker/hardware/raspberry.py` met echte drivers voor
   display/speaker/lamp/button; GPIO-pinnen pas dan vastleggen.
3. `main.build_default()` uitbreiden met `--hardware pi|mock`.
4. NTP-tijdsync controleren; autostart (systemd) inrichten.
5. Displayhelderheid/nachtmodus en lamphelderheid afstemmen op echte hardware.
6. Agenda-adapters één voor één onderzoeken en pas dan bouwen
   (geen scraping; OAuth-tokens in OS-keyring, nooit in JSON/logs).
7. Setup-API pas op LAN zetten (`--host`) met authenticatie/TLS (nu alleen
   `127.0.0.1` zonder auth, bedoeld voor prototype).

## Welke GPIO-informatie nog ontbreekt

Alles: pinnummers voor button/lamp/speaker, display-interface (I2C/SPI/HAT +
adres/bus), logica-niveaus en voedingsgegevens staan in
`docs/hardware-inventory.md` als open checklist. Niets is vooraf ingevuld.
"# slim" 
