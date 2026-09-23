# Architectuur — WaveSync, eerste prototype (v0.2)

## Doel en scope

Betrouwbare wekkerlogica die **zonder Raspberry Pi** op een laptop ontwikkeld
en getest kan worden, en later zonder herschrijven op echte hardware draait.

Eerste prototype: **display + speaker + lamp + één button + Raspberry Pi 5**.
Bewegingshardware is uitgesteld naar een latere prototypefase en maakt geen
deel uit van de eerste werkende versie.

## Ontwerpkeuzes (met reden)

| Keuze | Reden |
|---|---|
| Python 3.11+ (getest op 3.12) | Standaard op Raspberry Pi OS, goed voor GPIO, tijd, netwerk, opslag |
| Alleen stdlib als runtime-dependency | Minder risico op de Pi, geen `pip install`-breuk; setup-API met `http.server` i.p.v. Flask/FastAPI |
| `pytest` als enige dev-dependency | Tests zijn verplicht; meer tooling pas bij noodzaak |
| Core kent alleen `Protocol`-interfaces | `AlarmClock` importeert nooit GPIO; mocks en Pi-drivers zijn uitwisselbaar |
| `Clock`-interface i.p.v. `datetime.now()` | Deterministische tests via `FakeClock`; later evt. RTC/NTP-bron |
| Expliciete state machine met overgangstabel | Geen verspreide `if`-stapels; illegale overgangen gooien `IllegalTransitionError` |
| Eén button-controller met debounce | Eén fysieke druk is exact één actie; lamp-timer en alarm-afhandeling op één plek |
| Instellingen als gevalideerde dataclasses | Ongeldige waarden worden bij de grens geweigerd (API + opslag) |
| JSON-bestand met atomair schrijven | Simpel, SD-kaartvriendelijk, geen database nodig voor prototype |
| Adapterinterface + register voor agenda | Mock direct; Osiris via koppel-flow; overige melden eerlijk "nog niet beschikbaar" |
| Setup-API is dunne schil | Wekker werkt zelfstandig; telefoon is geen vereiste tijdens wekken |
| Touch-GUI leest alleen bestaande logica | Schermen als testbare layout-data (screens.py) + dunne tkinter-renderer; geen eigen alarm/agenda-logica |
| Auth-abstractie zonder wachtwoorden | AuthProvider-protocol + demo-flow met eenmalige states; echte Entree/OIDC later zonder GUI- of core-refactor |

## Moduleoverzicht

```text
src/wekker/
├── clock.py            Clock-protocol, SystemClock, FakeClock
├── settings.py         Gevalideerde dataclasses (alarm/lamp/display/agenda/locale)
├── storage.py          JsonStore (atomair schrijven)
├── logging_config.py   Redactie van wachtwoorden/tokens in logs
├── hardware/
│   ├── interfaces.py   Protocols: display/speaker/lamp/button
│   │                   (+ bewaarde motor/touch-protocols voor later, gemarkeerd UITGESTELD)
│   └── mock.py         Mock-implementaties met toestand + event-simulatie
├── alarm/
│   ├── state.py        AlarmState-enum (sleeping/ringing/snoozed/dismissed)
│   └── core.py         AlarmClock state machine + tick/snooze/dismiss
├── button/
│   └── controller.py   ButtonController: debounce + alarm-afhandeling + lamptimer
├── display/
│   └── manager.py      ScreenModel + render + auto-uit + nachtmodus + meldingen
├── agenda/
│   ├── models.py       Lesson (met source), DaySchedule (intern formaat)
│   ├── providers.py    AgendaProvider-protocol + register + MockAgendaProvider
│   ├── cache.py        Laatste rooster + syncstatus + stale-detectie
│   └── sync.py         AgendaSyncService (fouttolerant)
├── api/
│   └── server.py       Setup-API + mobiele setup-pagina + auth-endpoints (stdlib)
├── gui/
│   ├── screens.py      Navigator + schermdata + layouts (géén tkinter, testbaar)
│   └── app.py          tkinter-renderer, fullscreen 800x480, 1s-loop
├── sim.py              Simulatiemodus (echte core, nep-tijd, mocks)
└── main.py             Composition root + wekkerlus (1 Hz tick) + auto-sync
```

## Datastroom

```text
AgendaProvider → AgendaSyncService → AgendaCache → DisplayManager → DisplayDriver
Settings/API   → AlarmClock.tick() → Speaker/Lamp (via Protocols)
Button         → ButtonController → AlarmClock.dismiss() / Lamp-timer / Display-melding
```

## State machine

```text
SLEEPING --(wektijd bereikt / trigger)--> RINGING
RINGING  --(snooze)--> SNOOZED --(snooze voorbij)--> RINGING
RINGING / SNOOZED --(dismiss via button, physical=True)--> DISMISSED
DISMISSED --(nieuwe dag)--> SLEEPING
```

Regels:

- `dismiss()` zonder fysieke bevestiging wordt geweigerd (gelogd als warning).
- Elke dag gaat het alarm maximaal één keer automatisch af (`_last_trigger_date`).
- Transities zijn atomaire: eerst hardware-side-effects, dan pas de nieuwe
  toestand vastleggen. Faalt een driver, dan blijft de oude toestand staan en
  probeert `tick()` het later opnieuw (geen "stil alarm").
- `next_alarm()` geeft tijdens SNOOZED het einde van de snooze terug.
- Bij RINGING: speaker speelt (als `alarm.speaker_enabled`), lamp aan volgens
  alarmregels (als `lamp.on_with_alarm`), display toont `ALARM!`.
- Bij DISMISSED: speaker en lamp stoppen; het systeem keert terug naar normaal.

## Button-gedrag (gedocumenteerde keuze)

- Alarm actief (RINGING/SNOOZED) + druk → alarm afgehandeld, lamp uit.
- Geen alarm actief + druk → lamp aan voor `lamp.duration_after_button`
  seconden (default 30), timer reset bij nieuwe druk, automatisch uit.
- Drukken binnen 0,3 s na de vorige druk worden genegeerd (debounce).
- `shutdown()` zet de lamp altijd uit.
- De button wekt ook het display; de controller zet een korte melding
  ("Lamp aan (button)") die met de timer verdwijnt.

## Concurrency en opslag

- `AlarmClock`, `DisplayManager` en `ButtonController` zijn thread-safe
  (RLock): de setup-API draait in een eigen thread en GPIO-callbacks komen
  straks op eigen threads binnen, terwijl de wekkerlus 1 Hz tikt.
- De wekkerlus (`main.run_once`) vangt exceptions per tik op: één defecte
  driver mag het proces nooit stilzetten. `shutdown()` dooft de lamp.
- Bij onleesbare/corrupte instellingen start de wekker met veilige defaults
  (het bestand wordt niet overschreven; herstel via `POST /api/settings`).
- `JsonStore.save` schrijft atomair (tmp + fsync + replace).
- `ramp_up_seconds` is gereserveerd maar nog niet toegepast door de core:
  volume-/lichtopbouw wordt pas geïmplementeerd met echte hardware om te
  valideren. De setup-app mag het veld al tonen, maar moet het als
  "nog zonder effect" labelen.

## Agenda-versheid en providers

- Provider-register (`agenda/providers.py`): `mock` (direct, auth none),
  `osiris` (OSIRIS–ROC Aventus, auth `entree-oidc`, koppeling vereist),
  `somtoday`/`magister`/`myx` (geregistreerd maar `available=False`).
  GUI en webinterface gebruiken alleen `list_providers()` en de generieke
  `AgendaProvider`-interface — geen school-specifieke takken in core/GUI/API.
- Koppelingen (`agenda/auth.py`): `AuthService` bewaart alleen `AuthLink`
  (provider, accountlabel, demo-vlag — géén wachtwoorden/tokens).
  `MockEntreeAuth` simuleert de login-vorm met eenmalige, kort geldige states.
- `GET /api/agenda/status` geeft `stale`, `connected`, `linked` en
  `available_providers` terug; `GET /api/agenda/providers` de volledige
  registerlijst met koppelstatus; `GET /api/agenda/items` geeft lessen met
  `simulated`-vlag, 409 bij ontbrekende Osiris-koppeling of 501 bij
  niet-beschikbare platforms.
- Een mislukte sync (`status: error`) wist de cache nooit: oude lessen
  blijven zichtbaar, gemarkeerd als mogelijk verouderd.
- De wekkerlus synchroniseert periodiek volgens `agenda.auto_sync_minutes`
  (0 = uit). Echte adapters leveren lessen timezone-aware in de lokale
  systeemtijdzone (zie providercontract in `providers.py`).

## Touchscreen-GUI (`src/wekker/gui/`)

- `screens.py`: `Navigator` (links/rechts met wrap, uitbreidbaar via
  `register`), formatters (`HH:MM`/`uit`), `MainScreenData` (tijd + alarm),
  `AgendaScreenData` (provider, dag, max. 5 lessen, simulated-badge) en
  `main_layout`/`agenda_layout` als pure data. Headless getest.
- `app.py`: tkinter-renderer (lazy import, dus importeerbaar zonder display),
  kiosk 800x480 via overrideredirect + `-fullscreen`/`-topmost` (geen
  titlebar/panel; Alt+Tab vervalt), Escape sluit af, F11 schakelt fullscreen,
  1-seconde-loop (`run_once` + render).
- Starten: `python -m wekker gui` (Pi, fullscreen + web-API),
  `python -m wekker gui --window` (development). Details: `docs/touch-gui.md`.

## Simulatiemodus (`src/wekker/sim.py`)

- `Simulation` is een dunne schil: echte `AlarmClock`, `ButtonController`,
  `DisplayManager`, `AgendaSyncService` en gevalideerde instellingen, met
  `FakeClock` + mocks (geen motor/touch meer).
- Tijd loopt via `advance(seconden)`, seconde per seconde zonder `sleep`,
  met exact dezelfde tick-semantiek als de 1 Hz-weklus (`run_once`).
  Hardwarefouten worden per seconde gelogd (eventlog) zonder de simulatie
  te stoppen.
- CLI via `python -m wekker simulate` (REPL, `--demo` of `--commands`);
  `python -m wekker` zonder subcommand blijft de servermodus (backward
  compatible).
- Wat simulatie niet bewijst: GPIO-timing en hardware-debounce, LED-helderheid,
  geluidskwaliteit, stroomgedrag, netwerk — zie README.

## Wat later op de Pi moet gebeuren

1. Onderdelen fysiek controleren en `docs/hardware-inventory.md` aanvullen.
2. Nieuwe module `src/wekker/hardware/raspberry.py` met echte drivers voor
   display/speaker/lamp/button. GPIO-pinnummers liggen pas vast bij
   definitieve hardwarekeuze — **niet verzinnen in de core**.
3. `main.build_default()` uitbreiden met een `--hardware pi|mock` vlag.
4. Tijdsynchronisatie controleren (NTP/RTC) zodat het alarm bij stroomuitval klopt.
5. Agenda-adapters per platform onderzoeken — zie onder.

## Agenda-adapters: onderzoeksstatus

| Platform | Methode | Auth | Status |
|---|---|---|---|
| Mock | Ingebouwd | Geen | ✅ Werkend (voorbeeldgegevens, als zodanig gemarkeerd) |
| Osiris (ROC Aventus) | Voorbereide provider + demo-login | Entree/OIDC (nog te regelen, zie `docs/osiris-entree.md`) | Demo-koppeling werkend; echte API nog niet |
| Somtoday | Nog te onderzoeken | Onbekend (later OAuth/token) | Geregistreerd als "later" |
| Magister | Nog te onderzoeken (officiële API?) | Onbekend (later OAuth/token) | Geregistreerd als "later" |
| MyX | Nog te onderzoeken | Onbekend (later OAuth/token) | Geregistreerd als "later" |

Standaardaanpak: alleen officiële, gedocumenteerde API's met OAuth/API-keys.
Geen scraping of omzeiling als standaardoplossing. Geheimen horen in een veilige
opslag (bv. OS-keyring / Pi-secretbestand met strikte rechten), nooit in
`wekker-settings.json` of logs.

## Veiligheid en privacy

- `settings.py` heeft geen velden voor wachtwoorden/tokens (alleen providernaam).
- `logging_config.redact()` maskeert `password=`/`token=`/`bearer` in logregels.
- API draait standaard op `127.0.0.1`; voor LAN-gebruik expliciet `--host` kiezen
  en later authenticatie/TLS toevoegen (nog niet in prototype).
