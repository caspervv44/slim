# WakeSync — MyX Agenda zichtbaar maken (hotfix)

Deze hotfix is gemaakt voor de situatie:
- MyX synchronisatie: GELUKT
- 33 dagen in de cache
- 0 lessen vandaag
- 5 lessen in de komende 21 dagen
- Het Agenda-scherm toont toch geen rooster

## Oorzaak

De originele schermcode start de Agenda altijd op de huidige datum en haalt
alleen voor die geselecteerde datum lessen uit AgendaCache. Als vandaag leeg is,
lijkt het alsof er niets is gesynchroniseerd, terwijl toekomstige dagen wél
lessen bevatten.

Daarnaast kan een GUI die vanuit een andere werkmap of Python-installatie draait
een ander instellingenbestand en dus een andere cache gebruiken.

## Wat deze hotfix doet

- Als Agenda op vandaag staat en vandaag geen lessen heeft, opent deze vanzelf
  de eerstvolgende dag met lessen in de bestaande cache.
- De dagpijltjes springen naar de vorige/volgende gevulde lesdag.
- 'Nu' kiest bewust vandaag, ook als die datum leeg is.
- Het Vandaag-scherm toont de eerstvolgende toekomstige les als alle lessen
  van vandaag voorbij zijn of vandaag leeg is.
- Werkt ook als synchronisatie na het openen van de GUI voltooid wordt.
- Laat alle alarmen, sounds, themabestanden, sleep screens, credentials, MyX-URL,
  servercode en agendacache ongemoeid.

Er worden GEEN netwerkverzoeken gedaan vanuit deze UI-hotfix.

## Installeren op je Raspberry Pi

1. Pak de ZIP uit in je bestaande repository:
   `/home/casper/slim2/slim`
   (de relatieve mappen `src`, `tools` en `tests` komen daarmee op de juiste plek).
2. Open de terminal en voer uit:

```bash
cd ~/slim2/slim
source .venv/bin/activate
python3 tools/check_agenda_dates.py
python3 tools/apply_agenda_hotfix.py
python3 -m pip install -e .
python3 -m pytest -q tests/test_agenda_fix.py tests/test_installer.py
```

`check_agenda_dates.py` vertelt je op welke datums er lokaal lessen zijn en
detecteert of `python3 -m wekker` mogelijk een andere WakeSync-installatie gebruikt.
Hij toont GEEN geheime feedlink en GEEN lesnamen.

Controleer dat de patch echt wordt geladen:

```bash
python3 -c "from wekker.gui.app import TouchApp; print('Agenda-hotfix geladen:', getattr(TouchApp, '_wakesync_agenda_fix_installed', False))"
```

Verwachte melding: `Agenda-hotfix geladen: True`.

Sluit de oude GUI volledig af, inclusief eventueel nog lopende autostart-GUI.
Start de GUI opnieuw met exact hetzelfde instellingenbestand:

```bash
cd ~/slim2/slim
python3 -m wekker gui --settings "$PWD/wekker-settings.json"
```

Tik op **Agenda**. Als er vandaag niets is, wordt de eerste toekomstige
lesdag uit de cache geopend. Druk op **Nu** om vandaag leeg te zien, of op de
pijlen om tussen dagen met lessen te bladeren.

**LET OP**: als een autostart-/systemd-service de GUI vanuit een andere map
of met een ander `--settings`-bestand start, pas ook die opstartopdracht aan naar
dezelfde absolute instellingenlocatie. Anders leest die GUI mogelijk een andere
agendacache. Het diagnostische script geeft het verwachte pad aan.

## Uploaden naar GitHub

Na een geslaagde test kun je de gewijzigde bronbestanden via je normale
GitHub-werkwijze committen. Push nooit `wekker-settings.json`,
`.wakesync-agenda-cache.json` of geheime MyX-feedbestanden.

De hotfix past slechts `src/wekker/gui/app.py` aan en voegt
`src/wekker/gui/agenda_fix.py` toe; de extra tools en tests zijn optioneel.
De veilige originele versie van `app.py` staat buiten de repository, onder
`~/.local/share/wakesync-myx-agenda-hotfix/`.

## Ongedaan maken

```bash
cd ~/slim2/slim
python3 tools/apply_agenda_hotfix.py --undo
```

Dit weigert automatisch herstel wanneer je `app.py` intussen verder hebt bewerkt.

## Wat is getest?

- 33 cachedagen met 0 lessen vandaag, 5 lessen op toekomstige dagen;
- automatisch openen van de eerstvolgende gevulde lesdag;
- bladertoetsen naar de vorige/volgende lesdag;
- bewust tonen van een lege dag via 'Nu';
- GUI ververst na een later gevulde cache;
- geen lesdata verzinnen als de cache leeg is;
- idempotente installatie en gecontroleerd herstellen.

De tests gebruiken fictieve lokale gegevens; het echte Raspberry Pi-scherm
en jouw MyX-feed kunnen alleen op jouw apparaat definitief worden gevalideerd.
