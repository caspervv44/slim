# WakeSync v8 touchscreen-GUI — Waveshare 5-inch 800×480

## Bekende opstelling

De huidige WakeSync-prototypeopstelling is:

- Raspberry Pi 5;
- Raspberry Pi OS met Wayland/labwc;
- Waveshare 5-inch HDMI LCD, 800×480;
- inputdevice `ADS7846 Touchscreen`;
- Wayland-output op het geteste systeem: `HDMI-A-1`.

De kernel heeft op het geteste apparaat de ADS7846 al als inputdevice gezien.
Daarom hoeft WakeSync daar normaal alleen de labwc-mapping te corrigeren.

## GUI

De Tkinter-GUI gebruikt exact 800×480. Ondernavigatie heeft een gereserveerde
vaste zone en kan door een volle agenda niet worden weggedrukt.

Schermen:

- **Vandaag:** grote tijd + alarm; huidige/volgende les met tijd, docent en
  groot lokaal;
- **Agenda:** 4 kaarten per pagina, dag- en paginaknoppen, huidige les,
  pauze-/overlaplabels;
- **Instellingen:** Weergave, Online beheer, Software, Touchscreen & beeld,
  Diagnose;
- **Alarm:** eigen prioriteits-overlay met snooze en countdown;
- **Slaap:** donker WakeSync-scherm; geen claim dat de fysieke backlight uit is.

## Automatische touchconfiguratie

```bash
python -m wekker touch-setup --status
```

Bij bekende, reeds gedetecteerde ADS7846:

```bash
python -m wekker touch-setup
```

WakeSync maakt zo nodig een backup van `~/.config/labwc/rc.xml` en schrijft de
mapping:

```xml
<touch deviceName="ADS7846 Touchscreen"
       mapToOutput="HDMI-A-1"
       mouseEmulation="yes" />
```

Daarna wordt `labwc --reconfigure` geprobeerd.

Als ADS7846 níet gedetecteerd is, schrijft WakeSync niets aan bootconfig zonder
expliciete bevestiging van het hardwareprofiel. Voor het bekende profiel:

```bash
sudo .venv/bin/python -m wekker touch-setup \
  --profile waveshare-5-hdmi-ads7846 \
  --confirmed \
  --home "$HOME"
sudo reboot
python -m wekker touch-setup --verify
```

Een tweede uitvoering is idempotent.

## Bekende helderheidsbeperking

Op het huidige scherm was `/sys/class/backlight` leeg en meldde DDC/CI dat de
monitor geen DDC/CI ondersteunt. Daarom zijn hardware-backlight en donkere
slaapweergave twee verschillende dingen.
