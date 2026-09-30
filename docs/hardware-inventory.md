# Hardware-inventarisatie — WakeSync prototype

Status gebaseerd op het huidige testapparaat en de informatie uit het project.

| Onderdeel | Bekend | Status |
|---|---|---|
| Computer | Raspberry Pi 5 | bekend |
| OS | Raspberry Pi OS, Wayland/labwc | bekend op huidig apparaat |
| Scherm | Waveshare 5-inch HDMI LCD, 800×480 | bekend |
| Touchcontroller | ADS7846 Touchscreen | Linux detecteert inputevents |
| Wayland-output | `HDMI-A-1` op huidig apparaat | bevestigd met `wlr-randr` |
| Backlight sysfs | `/sys/class/backlight` leeg | geen standaard backlightdevice |
| DDC/CI | monitor reageert niet op slave-adres 0x37 / ondersteunt DDC/CI niet | niet bruikbaar |
| Speaker | definitief type/aansluiting nog niet vastgelegd | later |
| Flits/lamp | definitief type/aansluiting nog niet vastgelegd | later |
| Fysieke stopknop | productregel bestaat; definitieve GPIO-aansluiting nog niet vastgelegd | later |

## Touch

`evtest` zag `ADS7846 Touchscreen` met touch-capability. Daardoor is op het
huidige apparaat de kerneldriver actief; WakeSync v8 hoeft daar geen
boot-overlay te forceren en kan veilig alleen de labwc-outputmapping corrigeren.

Voor een schone installatie bestaat één expliciet profiel in
`touch_setup.py`. Gebruik dat alleen als het fysieke scherm exact het
Waveshare 5-inch HDMI/ADS7846-profiel is.

## Helderheid

De huidige displayhardware biedt geen bevestigde echte backlightinterface via
sysfs of DDC/CI. WakeSync mag een donkere slaapweergave tonen, maar mag dat
niet presenteren als fysiek uitgeschakelde backlight.

## Nog te bepalen voor echte alarmhardware

Vóór speaker/lamp/button-drivers worden toegevoegd:

- exact onderdeel/model;
- spanning en stroom;
- interface (USB/audio/GPIO/PWM);
- veilige GPIO-pinbezetting;
- voeding en eventuele transistor/driver;
- bootgedrag (lamp/speaker moet veilig uit blijven);
- meting op de echte hardware.

Geen motoren of bewegingshardware in de huidige v8-scope.
