# WakeSync Premium Themes — ontwikkelpatch voor 10.1.1

**Inhoud:** vier rijke visuele thema's op de vier bestaande schermen, voor de
Raspberry Pi 5 met 5-inch 800×480-scherm.

De bron op GitHub meldt versie **10.1.1** in `pyproject.toml` en
`src/wekker/__init__.py` (gecontroleerd 12 oktober 2026).
De openbare repository heet:
https://github.com/caspervv44/slim

## Wat er wel en niet verandert

- Nieuw: Midnight Glass, Aurora Slate, Light Executive, Ember Noir.
- Nieuw: premium klokring, bergillustraties, transparante kaarten, bovenste
  navigatie en visuele schakelaars.
- Vier pagina's: **Vandaag**, **Agenda**, **Alarm** en **Instellingen**.
- De opgeslagen themacodes blijven `midnight`, `ocean`, `light`, `amber`.
- De bestaande alarmen, klokbron, MyX/ICS-agenda, online beheer,
  software-updater, veiligheidstests en instellingenopslag worden niet vervangen.
- Bij een gekozen alarm blijft het bestaande uitgebreide configuratiepaneel
  beschikbaar; de originele alarmmaker en instellingspanelen worden behouden.
- Het officiële **wakesync-logo.png** moet al in de repository staan. De
  installatie stopt als dit ontbreekt; de merkpixels blijven onaangetast.

**Dit is een ZIP met gewijzigde/toegevoegde bestanden, geen volledige kopie van
GitHub.** De originele projectbestanden blijven de basis. Dit pakket verandert
de officiële versienaam niet en is nog niet fysiek op een Raspberry Pi getest.

## Installeren in je lokale GitHub-clone

Download de ZIP, plaats het bestand naast of in je werkmap en voer in de
map met `pyproject.toml` uit:

```bash
cd ~/slim
unzip -o /pad/naar/WakeSync-Premium-10.1.1-themapatch.zip -d .
source .venv/bin/activate
python3 tools/apply_premium.py

python3 -m compileall -q src tests
python3 -m pytest -q
python3 -m wekker healthcheck
python3 -m wekker gui --window
```

Het activeringsscript controleert of de basisversie **10.1.1** is, de
GUI-instantiatie precies overeenkomt met de verwachte broncode, en het officiële
logo aanwezig is. Het slaat de originele `gui/app.py` op buiten je Git-map,
onder `~/.local/share/wakesync-premium/`.

Bij een onverwachte projectstructuur stopt de installatie zonder de GUI te
overschrijven.

## Push naar GitHub

Na controle op je eigen computer:

```bash
git status
git add src/wekker/gui/app.py src/wekker/gui/premium.py \
  src/wekker/gui/premium_render.py src/wekker/assets/premium_*.png \
  tools/apply_premium.py tools/remove_premium.py \
  tools/generate_premium_previews.py tests/test_premium_render.py \
  tests/test_premium_installer.py docs/PREMIUM_THEMES.md
git commit -m "WakeSync: vier premium thema's voor touchscreen"
git push origin main
```

Voeg alleen bedoelde bronbestanden toe; zet nooit privéconfiguraties,
accountgegevens of verborgen runtimebestanden op GitHub.

## Raspberry Pi

Zoals in de bestaande workflow:

```bash
cd ~/slim
git pull --ff-only
source .venv/bin/activate
python3 -m pip install -e ".[dev]"
python3 -m pytest -q
python3 -m wekker healthcheck
python3 -m wekker gui
```

Start bij gebruik van een eigen kiosk-service de GUI volgens jouw bestaande
serviceprocedure. De patch verandert die configuratie niet.

## Terugdraaien

Vanuit je lokale clone:

```bash
python3 tools/remove_premium.py
```

Daarna kun je ook deze terugdraaiwijziging committen en pushen. Het script
wijzigt geen alarm-, MyX-, cloud- of gebruikersconfiguratie.

## Voorbeelden en beperkingen

`previews/` bevat vier 2×2-overzichten die door dezelfde nieuwe
rendercode zijn gemaakt, met **fictieve demonstratiegegevens**.
Het previewproces kan zonder originele GitHub-assets geen echt C9-logo tonen;
op de Raspberry Pi wordt **altijd het bestaande originele logobestand**
gebruikt. Er wordt geen nieuw merklogo meegeleverd.

Nieuwe voorbeeldbeelden maken:

```bash
python3 tools/generate_premium_previews.py
```

Op dit apparaat zijn 25 gerichte render-/installer-tests geslaagd. Voor
een productierelease zijn nog hardwarechecks nodig: touchcontroller,
snelheid op de Pi, alarmsignaal, MyX-sync, overlays en de echte schermhelderheid.
De ontwerpen zijn voor de 800×480-app vertaald en geen gegarandeerde
pixel-perfecte reproductie van de eerder getoonde AI-conceptfoto's.
