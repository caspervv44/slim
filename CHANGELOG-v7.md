# WakeSync v7.0.0

## Nieuw

- Productnaam en zichtbare branding gewijzigd naar WakeSync.
- Nieuw WakeSync-logo in de touchscreeninterface.
- Donkere slaapmodus met logo, tijd en datum.
- Instelbare slaapvertraging en slaapweergave, lokaal én via veendomain.nl.
- Ingebouwde software/firmware-updater via GitHub met backup, rollback en automatische herstart.
- Compactere instellingenpagina die volledig binnen 800×480 past.
- Software/firmware-updater zichtbaar in Instellingen.
- Cloudstatus toont revision en laatste synchronisatie.
- Startup-splash met WakeSync-branding.

## Verbeterd

- Navigatie blijft onderaan gereserveerd, ook bij volle agendadagen.
- MyX/Xedule-lokaalextractie is robuuster.
- Cloudrevision wordt pas bevestigd nadat de Pi een webwijziging succesvol heeft toegepast.
- Helderheidsdetectie blokkeert de touchscreen-GUI niet meer.
- xrandr wordt onder Wayland niet als backlightfallback gebruikt.
- Lokale webapp op poort 8080 wordt niet meer als productinterface gestart.
- QR-code blijft lokaal beschikbaar en kan schermvullend worden geopend.
- Thema's Midnight, Ocean, Light en Amber blijven lokaal en online instelbaar.

## Server

- `test2.pl` service: `wakesync`
- server/API versie: 7
- slaapmodusinstellingen toegevoegd aan de webinterface en cloudvalidatie.

## Updaten vanaf v6

De eerste installatie van v7 moet handmatig gebeuren. Vanaf v7 kunnen volgende
versies via **Instellingen → Software / firmware updater** worden geïnstalleerd.
