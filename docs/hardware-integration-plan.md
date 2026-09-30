# Hardware-integratieplan — WakeSync v8

## Bevestigde prototypehardware

De software is nu afgestemd op de onderdelen die daadwerkelijk van het huidige
prototype bekend zijn:

- Raspberry Pi 5;
- Raspberry Pi OS met Wayland/labwc;
- Waveshare 5-inch HDMI LCD, 800×480;
- touchdevice `ADS7846 Touchscreen`;
- actieve Wayland-output op het geteste apparaat: `HDMI-A-1`.

Op het huidige scherm is `/sys/class/backlight` leeg en de monitor meldt geen
DDC/CI-ondersteuning. De donkere WakeSync-slaapweergave is daarom **geen**
garantie dat de fysieke backlight uit of gedimd is.

## Touch/displayprofiel

WakeSync v8 bevat het profiel:

```text
waveshare-5-hdmi-ads7846
```

Als Linux ADS7846 al detecteert, corrigeert WakeSync alleen de labwc-mapping en
laat bootconfig ongemoeid. De beoogde mapping is:

```xml
<touch deviceName="ADS7846 Touchscreen"
       mapToOutput="HDMI-A-1"
       mouseEmulation="yes" />
```

Voor een schone installatie waar de driver niet wordt gedetecteerd, mag de
profielspecifieke bootconfig alleen na expliciete bevestiging worden gebruikt.
Voor iedere wijziging wordt een backup gemaakt; een tweede uitvoering hoort
geen nieuwe wijziging te veroorzaken.

## Hardware die nog niet definitief is

De productpresentatie kan toekomstige lamp/geluidsfuncties beschrijven, maar
v8 claimt nog geen werkende fysieke driver voor:

- speaker of buzzer;
- flits-/wake-uplamp;
- fysieke alarmknop/aansluitpin.

Pinnen worden pas vastgelegd nadat de werkelijke onderdelen en elektrische
aansluiting zijn gecontroleerd.

## Softwarecontracten voor latere drivers

`wekker.hardware.interfaces` blijft de scheiding tussen alarmcore en hardware.
Een echte driver moet dezelfde semantiek als de mocks volgen:

- `Speaker.play(...)` / `stop()` mogen fouten niet stil inslikken;
- `Lamp.on(...)` / `off()` moeten een veilige uittoestand ondersteunen;
- de fysieke stopknop levert precies één gevalideerde actie per druk;
- de alarmcore commit zijn toestand pas nadat de bijbehorende hardwareactie
  succesvol is afgerond.

Daardoor kan een eenmalige driverfout worden herprobeerd zonder half
gecommitte snooze- of dismissstatus.

## Aansluit- en testvolgorde voor toekomstige hardware

1. **Pi en scherm** — touch/output/NTP en v8-healthcheck controleren.
2. **Speaker alleen** — laag volume, play/stop en foutgedrag testen.
3. **Lamp alleen** — elektrische driver en default-uit veilig controleren.
4. **Fysieke knop alleen** — debounce en 20 opeenvolgende drukken testen.
5. **Integratie** — complete `SLEEPING → RINGING → SNOOZED/DISMISSED`-cyclus.

Gebruik voor GPIO op een Pi 5 bij voorkeur een actuele gpiozero/lgpio-route en
gok nooit pinnen of spanningsniveaus. Een lamp met relevante stroom hoort via
een geschikte driver/transistor/relais en niet rechtstreeks aan een GPIO-pin.

## Niet in v8

V8 flasht geen kernel, volledig Raspberry Pi OS of EEPROM/bootloader. Ook
beweging/motoren maken geen deel uit van het huidige productplan.
