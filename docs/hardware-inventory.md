# Hardware-inventarisatie — Aventus Wekker, eerste prototype

Datum: 2026-09-17. Status: **er is nog geen fysieke hardware waargenomen of
aangesloten.** Alles hieronder wat niet onder "platformachtergrond" staat is
**ONBEKEND** en moet worden aangevuld zodra de onderdelen er zijn. Er worden
geen aannames als feiten gepresenteerd; open vragen staan als ❓ gemarkeerd.

Eerste prototype: **display + speaker + lamp + één button + Raspberry Pi 5**.
Bewegingshardware is uitgesteld naar een latere prototypefase en maakt geen
deel uit van de eerste werkende versie.

## 1. Platformachtergrond Raspberry Pi 5 (openbaar, verifiëren op apparaat)

Dit zijn geen projectgegevens maar openbare platformfeiten, bedoeld om verkeerde
keuzes (zoals RPi.GPIO) voor te zijn. Verifieer op het apparaat met de genoemde
commando's voordat je drivers kiest.

| Onderwerp | Stand van zaken (september 2026) | Verifiëren met |
|---|---|---|
| GPIO-aansturing | **RPi.GPIO werkt NIET op de Pi 5** (nieuwe RP1-I/O-chip; registers zitten niet meer op de hoofdprocessor). Gebruik **gpiozero** (aanbevolen, vooruit geïnstalleerd op Raspberry Pi OS, met lgpio-backend) of **lgpio** direct. `rpi-lgpio` is alleen een opvang voor oude RPi.GPIO-code. | `pinout`, `gpioinfo` |
| GPIO-chip | Op de Pi 5 zit de 40-pins header op een andere gpiochip dan op oudere modellen (RP1, i.p.v. chip 0). gpiozero 2.x kiest dit zelf; bij problemen expliciet de lgpio-factory met de juiste chip instellen. | `gpioinfo`, `ls /dev/gpiochip*` |
| OS / Python | Raspberry Pi OS (Debian-basis) met Python 3.11+; gpiozero en lgpio zitten in de apt-repositories (`python3-gpiozero`). Voor pip-installatie van lgpio zijn `python3-dev`, `swig` en `liblgpio-dev` nodig. | `cat /etc/os-release`, `python3 --version`, `apt list --installed \| grep -i -E "gpio|lgpio"` |
| Voeding | De Pi 5 wil officieel 5V/5A via USB-C; bij zwaardere USB-belasting of HATs is een tekort aan stroom een klassieke bron van vage fouten. Motoren krijgen **altijd een eigen voeding**, nooit via de 5V-pin van de header. | Officiële voeding controleren |
| Gereserveerde pinnen | Ingeschakelde interfaces (I2C, SPI, UART, 1-Wire) reserveren "hun" pinnen in de kernel; die zijn dan niet als gewone GPIO te claimen (`GPIO busy`). | `gpioinfo`, `sudo raspi-config` (Interface Options) |

## 2. Componentenstatus (project)

| # | Onderdeel | Merk/model | Interface | Voeding | Driver/bib | Status |
|---|---|---|---|---|---|---|
| 1 | Raspberry Pi 5 | ❓ (variant/RAM onbekend) | — | ❓ (officiële 5V/5A?) | Raspberry Pi OS ❓ (versie?) | ONBEKEND |
| 2 | 5-inch touchscreen (opgave project) | 800x480, touch aanwezig | Waarschijnlijk HDMI (beeld) + USB (touch) — **verifiëren op apparaat** | Via Pi (USB) | tkinter fullscreen (geen driver nodig) | DEELS BEKEND |
| 3 | Speaker | ❓ (passief/actief, USB / 3,5mm / HAT / GPIO-zoemer?) | ❓ | ❓ | ❓ (`aplay`? pygame? gpiozero-tones?) | ONBEKEND |
| 4 | Lamp / LED | ❓ (LED-strip, power-LED, relais?) | ❓ (GPIO+transistor/relais? PWM voor dimmen/knipperen?) | ❓ (eigen voeding bij >20 mA!) | gpiozero (waarschijnlijk) | ONBEKEND |
| 5 | Eén fysieke button (boven op speaker) | ❓ (maakcontact?) | GPIO digitaal in (met pull-up/down; debounce in software) | — (signaal) | gpiozero `Button` | ONBEKEND |
| 6 | Voeding totaal | ❓ | — | ❓ | — | ONBEKEND |
| — | Wielen / motoren / motorcontroller | — | — | — | — | UITGESTELD naar latere fase |
| — | Touchsensoren (oppakken/aanraken; níet het touchscreen zelf) | — | — | — | — | UITGESTELD naar latere fase |
| — | Extra buttons | — | — | — | — | UITGESTELD naar latere fase |

## 3. Wat per onderdeel nog ontbreekt (checklist voor bij de hardware)

- [ ] Exacte merk + typenummer van elk onderdeel (foto + bon bewaren).
- [ ] Display: paneeltype, resolutie, interface (I2C-adres? SPI? HAT?), logica-niveau (3,3V vs 5V — **Pi-GPIO is niet 5V-tolerant**), bestaande Python-voorbeeldcode van de fabrikant.
- [ ] Speaker: actief of passief; aansluiting; hoe geluid afgespeeld wordt.
- [ ] Lamp: stroomopname (bepaalt transistor/relais + eigen voeding), dimbaar via (hardware-)PWM?
- [ ] Button: bedrading (pull-up of pull-down), prelgedrag.
- [ ] Voedingen: welke netvoeding voor Pi en lamp; gemeenschappelijke massa (GND) gepland.
- [ ] Raspberry Pi OS-versie + Python-versie op het apparaat (`cat /etc/os-release`).
- [ ] GPIO-pinnen: **nog nergens vastgelegd**; pas invullen na `gpioinfo`-controle (zie integratieplan §3).

## 4. Bekende risico's en beperkingen (nu al rekening mee houden)

1. **GPIO max. ~16 mA per pin, 3,3V, niet 5V-tolerant.** Lamp direct op een pin = defecte Pi. Altijd via transistor/relais/driver met eigen voeding bij >20 mA.
2. **Onverwacht starten:** GPIO-pinnen hebben bij boot een default-toestand; de lampschakeling moet zo gekozen/bedraad zijn dat de lamp bij opstarten **uit** blijft.
3. **RPi.GPIO-valkuil:** veel tutorials gebruiken het; op de Pi 5 doet het niets of gooit het fouten. Alleen gpiozero/lgpio gebruiken.
4. **Display is de grootste onbekende:** een I2C-karakterdisplay, SPI-matrix en HAT vragen elk een totaal andere driver. Hier valt niets zinnigs te schrijven tot het paneeltype bekend is.
5. **"Het werkte op de laptop" bewijst geen fysica:** timing, helderheid, geluidsdruk en stroomgedrag zijn pas op het apparaat te valideren (zie integratieplan, testfases).
