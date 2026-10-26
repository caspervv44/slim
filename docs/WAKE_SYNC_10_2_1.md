# WakeSync 10.2.1 — wijzigingsnotities

## Oorzaak van de niet-reagerende instellingenknoppen

`_settings_tile` verwacht achtereenvolgens een icoon, actie en optionele payload.
Software en Diagnose gebruikten eerder respectievelijk `software` en `diagnostics`
als actie. `_premium_click` handelde daarentegen `settings` af met de sectienaam als
payload. Er werd daardoor geen bijbehorende tak uitgevoerd.

De renderer levert nu `("settings", "software")` en `("settings", "diagnostics")`.
De dispatcher accepteert daarnaast expliciet de oude losse actienamen.
De installer leest de echte TouchApp en legt de bestaande handlers vast in
`src/wekker/gui/settings_routes_v1021.py`. Geen alternatieve software-updater,
kalibratietool of netwerkcontrole wordt achter deze knoppen geïmproviseerd.

## Formaten op het 800×480-scherm

| Onderdeel | Voor | Na |
|---|---:|---:|
| Zichtbare hoofdtabs: hoogte | 42 px | 54 px (+29%) |
| Raakhoogte hoofdtabs | 46 px | 58 px (+26%) |
| Middelpunt hoofdtabs | circa y=41 px | circa y=47 px |
| Agenda-dagpijlen: zichtbaar | 40×28 px | 51×42 px |
| Agenda-paginaknoppen: hoogte | 37 px | 48 px (+30%) |
| Alarm toevoegen: hoogte | 34 px | 44 px (+29%) |
| Alarmschakelaar | 38×23 px | 48×32 px |
| Thema-selectie instellingen: hoogte | 43 px | 54 px (+26%) |
| Thema-selectie detail: hoogte | 50 px | 64 px (+28%) |
| Detailknop Terug: hoogte | 36 px | 48 px (+33%) |
| Geluid testen: hoogte | 34 px | 46 px (+35%) |
| Alarm verwijderen: hoogte | 35 px | 46 px (+31%) |

Brede kaartknoppen die al groot waren blijven op dezelfde plek en even groot.
De compacte knoppen zijn niet allemaal in beide richtingen 50% vergroot: dat zou
vier tabs en zes agenda-regels niet meer netjes laten passen. De klikgebieden
blijven gescheiden. Thematische achtergronden en bestaande logo-assets blijven
hetzelfde.

## Startvoorzieningen

Het desktopbestand en de gebruikersopdracht verwijzen naar de eigen clone en venv.
De Python-starter houdt een proceslock vast terwijl zijn GUI-kindproces draait.
Een tweede start vraagt het bestaande premium-venster naar voren.

De installatie maakt een beheerd labwc-autostartblok; systeemautostart wordt niet
weggelaten wanneer labwc zonder --merge-config draait. De gekalibreerde rc.xml
wordt niet aangepast. Shellprofielen krijgen alleen een idempotent PATH-blok.

### Technische referenties

- labwc-autostart, configuratiezoekvolgorde en --merge-config:
  https://labwc.github.io/labwc-config.5.html
- Desktop Entry Exec-quoting:
  https://specifications.freedesktop.org/desktop-entry/latest/exec-variables.html
- Desktop-autostart is gekoppeld aan het starten van een aangemelde desktopsessie:
  https://specifications.freedesktop.org/autostart/latest/

De implementatie gebruikt voor deze Raspberry Pi expliciet labwc-autostart,
niet een rootservice en niet een wijziging aan display-/touchconfiguratie.
