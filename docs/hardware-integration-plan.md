# Hardware-integratieplan — laptop-simulatie → Raspberry Pi 5

Eerste prototype: **display + speaker + lamp + één button + Raspberry Pi 5**.
Bewegingshardware is uitgesteld naar een latere prototypefase en maakt geen
deel uit van de eerste werkende versie.

Uitgangspunt: de architectuur blijft staan. De core kent alleen Protocols;
`wekker.hardware.mock` blijft bestaan voor laptop en regressietests; echte
drivers komen in een nieuwe module `wekker.hardware.raspberry` met dezelfde
methodenamen. **Er wordt in dit document geen enkele definitieve pin
vastgelegd** — de pinout-tabel hieronder is leeg en wordt pas ingevuld als de
onderdelen bekend zijn (zie `docs/hardware-inventory.md`).

## 1. Beoordeling bestaande interfaces (`hardware/interfaces.py`)

| Interface | Methode | Geschikt voor echte hardware? | Opmerking / contract |
|---|---|---|---|
| DisplayDriver | `show(lines)` | ✅ ja, mits | Driver moet **graceful omgaan met willekeurige regelaantallen** (tronceren/scrollen naar paneelgrootte). Paneelafmetingen horen in de driver, niet in de manager. |
| DisplayDriver | `clear()` | ✅ ja | — |
| DisplayDriver | `set_brightness(0..100)` | ✅ ja | Driver vertaalt naar paneelbereik; buiten bereik → `ValueError` (zoals de mock). |
| Speaker | `play(sound, volume)` | ✅ ja, mits | `sound` is nu een naam (`"beep"`); echte driver mapt namen op geluidsbestanden/apparaat. Volume-ramp (`ramp_up_seconds`) is gereserveerd en wordt pas met echte hardware gevalideerd. |
| Speaker | `stop()` / `is_playing` | ✅ ja | `stop()` moet altijd veilig zijn, ook als er niets speelt. |
| Lamp | `on(brightness, blink, pattern)` | ✅ ja | `pattern` ∈ {steady, blink, pulse}; driver implementeert via (hardware-)PWM of relais. Fysieke betekenis van patronen kalibreren op het apparaat. |
| Lamp | `off()` / `is_on` | ✅ ja | — |
| Button | `on_press(handler)` | ✅ ja | Echte driver registreert GPIO-events; software-debounce zit in `ButtonController` (0,3 s), dus prellen is geen driver-eis. Handler loopt op een eigen thread (core is RLock-beveiligd). |
| TouchSensor | `on_touch(handler)` | ⏸️ uitgesteld | Protocol bewaard voor later; geen onderdeel van dit prototype. |
| MotorController | `drive_to(target)` / `stop()` / `is_driving` | ⏸️ uitgesteld | Bewegingshardware is uitgesteld naar een latere prototypefase en maakt geen deel uit van de eerste werkende versie. |

**Conclusie:** de interfaces zijn voldoende voor de eerste integratie. Er is
**geen interface-wijziging nodig**; wel gelden de hardwarecontracten uit de
module-docstring (idempotentie, fouten doorgooien i.p.v. slikken) onverkort
voor elke echte driver. De laptop-simulatie (`python -m wekker simulate`)
blijft de regressietest voor alle software boven de driverlaag.

## 2. Driverplan per onderdeel (aanpak, geen pinnen)

| Onderdeel | Waarschijnlijke aanpak | Definitief te kiezen zodra bekend |
|---|---|---|
| Eén button (boven op speaker) | gpiozero `Button` (pull-up/down); debounce in `ButtonController` | Pinnummer, pull-richting |
| Lamp | GPIO via transistor/relais; dimmen/knipperen via hardware-PWM waar mogelijk (gpiozero `PWMLED`), anders software-PWM | Stroomopname, PWM-geschiktheid |
| Speaker | Afhankelijk van type: `aplay`/pygame voor bestanden, gpiozero-tones voor zoemer; `play`/`stop` als dunne wrapper | Speakertype |
| LED-display | **Volledig paneel-afhankelijk** (I2C/SPI/HAT-bibliotheek van fabrikant); eigen klasse met `show`/`clear`/`set_brightness`, troncering naar paneelgrootte | Paneeltype + interface + logica-niveau |
| Klok | `SystemClock` blijft voldoen; op de Pi NTP controleren (`timedatectl`) en bij stroomuitval een RTC/HAT overwegen | NTP-status op apparaat |

Integratievolgorde in code (pas als hardware er is): één driver per keer in
`wekker/hardware/raspberry.py` met fabrieksfunctie, `--hardware pi|mock`-vlag
in `main.build_default()`, en per driver eerst het bijbehorende fase-testje
uit §3 groen voordat de core ermee verbonden wordt.

## 3. Pinout (leeg — pas invullen bij bekende hardware)

| Functie | GPIO (BCM) | Fysieke pin | Interface | Opmerking |
|---|---|---|---|---|
| Button | ❓ | ❓ | GPIO in | pull-richting noteren; debounce in software |
| Lamp | ❓ | ❓ | ❓ (PWM?) | via driver, nooit direct |
| Display | ❓ | ❓ | ❓ (I2C/SPI/HAT) | adres/bus noteren |
| Speaker | ❓ | ❓ | ❓ | type noteren |
| Voeding lamp | — | — | eigen voeding bij >20 mA | GND gemeenschappelijk |

Regel: pinnen pas invullen na `gpioinfo`-controle op vrije lijnen.

## 4. Benodigde libraries (geverifieerd voor Pi 5, september 2026)

| Library | Bron | Waarvoor | Status Pi 5 |
|---|---|---|---|
| `gpiozero` (2.x) | apt `python3-gpiozero` (vooruit geïnstalleerd op Pi OS) of pip | Button-events, lamp-PWM; kiest zelf de lgpio-backend | ✅ aanbevolen |
| `lgpio` | apt of pip (`python3-dev`, `swig`, `liblgpio-dev` nodig bij pip-build) | Directe GPIO-toegang als gpiozero tekortschiet; gpiochip van de header op de Pi 5 is **niet** chip 0 | ✅ |
| `rpi-lgpio` | pip | Alleen opvang voor bestaande oude RPi.GPIO-code; **niet** voor dit project | n.v.t. |
| `RPi.GPIO` / `pigpio` | — | **Niet gebruiken op de Pi 5** (RP1-chip; registers onbereikbaar) | ❌ |
| Display/speaker | fabrikant-specifiek | Pas te kiezen bij bekend paneel-/speakertype | ❓ |

Onze runtime blijft stdlib-only; gpiozero/lgpio komen er pas bij als
optionele Pi-dependency zodra de eerste echte driver geschreven wordt.

## 5. Testplan eerste aansluiting (volgorde is verplicht)

**Fase 0 — Pi-basis.** OS- en Python-versie noteren; `pinout`, `gpioinfo`,
`timedatectl` (NTP-sync!); `python3-gpiozero` aanwezig; venv + project
installeren; `pytest -q` op de Pi groen (software-regressie op het apparaat).

**Fase 1 — Display alleen.** Fabrikant-voorbeeldscript draaien; daarna
`show`/`clear`/`set_brightness`-equivalent testen incl. lange regellijst
(troncatie!) en helderheid 0/100. Acceptatie: leesbaar op armlengte, ook gedimd.

**Fase 2 — Speaker alleen.** Stilste volume eerst, opbouwen; `stop()` tijdens
afspelen; acceptatie: hoorbaar uit bed, `is_playing` klopt.

**Fase 3 — Lamp alleen.** Eerst meting/indicatie dat de schakeling klopt,
dan kort aan op lage helderheid; patronen steady/blink/pulse beoordelen;
acceptatie: fel maar veilig, `off()` werkt altijd.

**Fase 4 — Button alleen.** 20x drukken, vals-positieven tellen; acceptatie:
elke druk precies één actie (debounce!), geen spook-events. Daarna button
tegen actief alarm testen (afhandeling + lamp uit).

**Fase 5 — Integratie met de core.** Eén driver tegelijk via `--hardware`-vlag;
eerst `python -m wekker simulate --demo` als software-regressie, daarna echte
alarmcyclus; acceptatie: zelfde toestandsverloop als de simulatie
(`SLEEPING → RINGING → DISMISSED` via de button).

## 6. Veiligheidsmaatregelen

1. Lamp bij >20 mA op **eigen voeding** met passende driver (transistor/relais);
   nooit direct op een GPIO-pin; GND gemeenschappelijk met de Pi.
2. Power-on-gedrag vastleggen: bij boot moeten lamp (en later: motoren) **uit**
   blijven; verifiëren vóór integratie.
3. Software detecteert fouten (drivers gooien door, lus + core blijven
   consistent — al getest met mocks), maar software is **geen** vervanging
   voor 1–2.
4. 3,3V-logica respecteren: geen 5V-signalen op GPIO; bij twijfel level-shifter.
5. `shutdown()` dooft de lamp altijd (al in code + getest); bij stroomuitval
   helpt alleen hardware-matiging (schakeling default-uit).

## 7. Wat code-matig nog moet gebeuren (later, niet nu)

- Onderdelen fysiek controleren en `docs/hardware-inventory.md` aanvullen.
- `wekker/hardware/raspberry.py` met één driver per onderdeel (display,
  speaker, lamp, button) + fabrieksfunctie.
- `--hardware pi|mock`-vlag in `main.build_default()` (mocks blijven default).
- Display-regelbreedte en lamphelderheid afstemmen zodra de hardware bekend is.
- Pas daarna: agenda-adapters, Wi-Fi-setup, LAN-authenticatie/TLS voor de setup-API.

**Niet doen:** pinnen gokken, display-/speakerd driver schrijven zonder
onderdeeltype, hardware "werkend" noemen zonder fase-test, simulatie
verwijderen, core herschrijven.
