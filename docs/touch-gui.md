# Touchscreen-GUI — 5-inch 800x480 (Aventus Wekker)

## Overzicht

Fullscreen GUI voor het 5-inch 800x480 touchscreen (HDMI LCD + touch) op de
Raspberry Pi 5. Hoofdinterface van de fysieke wekker. Gebouwd met **tkinter**
(stdlib): geen extra dependencies, werkt op Raspberry Pi OS én op de laptop.

Belangrijkste eigenschappen:

- Resolutie 800x480, fullscreen via het `-fullscreen`-attribuut — géén
  `override-redirect`, dus de windowmanager blijft actief en **Alt+Tab werkt**.
  De GUI vervangt de desktop niet.
- **Escape** sluit af (development/testen), **F11** schakelt fullscreen.
- Grote tekst (klok ±130pt, pijlen ±56pt) en grote touch targets.
- Rustig ontwerp: per scherm één onderwerp, geen overvolle interface.
- Alle data komt uit de bestaande Runtime (core/settings/agenda). De GUI
  heeft **geen eigen alarm- of agendalogica**.

## Architectuur

```text
wekker/gui/screens.py   pure logica: Navigator, schermdata, layout-dicts
                        (géén tkinter → headless testbaar)
wekker/gui/app.py       tkinter-renderer + 1-seconde-loop (run_once + render)
```

`layout_for(navigator, data)` beschrijft het actieve scherm als data; de app
rendert die naar widgets. Later echte Osiris-data gebruiken vraagt dus geen
GUI-refactor: alleen de data verandert.

## Schermen en navigatie

- **MAIN**: grote tijd, daaronder `Alarm HH:MM`, links `<`, rechts `>`.
- **AGENDA**: providernaam (bv. `OSIRIS`), `Vandaag`, max. 5 lessen als
  `09:00  Wiskunde`, `demo-data`-badge bij gesimuleerde data,
  `Geen lessen vandaag` als het leeg is, links `<` terug.
- Linker pijl = vorig scherm, rechter pijl = volgend scherm (wrap).
- Uitbreidbaar: `Navigator.register(...)` voegt schermen toe; pijlen bladeren
  er automatisch doorheen.

## Starten

```powershell
# Raspberry Pi (fullscreen):
python3 -m wekker gui

# Development op laptop (venster 800x480):
python3 -m wekker gui --window

# Webinterface erbij (zelfde proces, zie README):
python3 -m wekker gui --host 0.0.0.0 --port 8080
```

De GUI start ook de web-API in hetzelfde proces (achtergrondthread), zodat
telefoon én touchscreen tegelijk werken. Afsluiten: Escape (of Ctrl+C in de
terminal); de lamp gaat via de normale shutdown uit.

## Testen

- Geautomatiseerd (headless): `python -m pytest tests/unit/test_gui.py -q`
  (navigator, layouts, formattering, agenda-mapping, Runtime-koppeling).
- Handmatig: `python -m wekker gui --window` — controleer klok, alarmtijd,
  beide pijlen, agendascherm met (demo-)lessen en Escape-afsluiting.
- Op de Pi: `python3 -m wekker gui` — controleer fullscreen, touchrespons en
  Alt+Tab naar de desktop en terug.
