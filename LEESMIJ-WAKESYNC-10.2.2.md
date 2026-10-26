# WakeSync 10.2.2 — Alarm stoppen en werkend geluid

Deze update is gebaseerd op de **werkelijke `src/wekker`-broncode** die je vanuit je
huidige GitHub-repository hebt geüpload. Het is een kleine patch boven op 10.2.1,
geen compleet nieuw project.

## Dit is opgelost

- Een grote rode knop **Alarm stoppen** op het touchscreen, bij **afgaan** én **Snooze**.
- Snooze blijft beschikbaar zolang het alarm klinkt. Tijdens Snooze blijft stoppen mogelijk.
- De fysieke knop blijft later bruikbaar, maar is niet langer nodig om te stoppen.
- Lampbediening is voorlopig weggehaald uit premium alarmen, klassieke alarmconfiguratie
  en het lokale browserdashboard. De bestaande opgeslagen instellingen blijven bewaard.
- De ALSA-driver kiest indien mogelijk de sessie-uitgang (Pulse/PipeWire) en kan
  anders de **USB Audio Device** direct aanspreken met `plughw:CARD=Device,DEV=0`.
  Een werkende USB-kaart krijgt geen stille HDMI-fallback.
- De audio-testknop en het webdashboard kunnen een ALSA-fout tonen.
- `wakesync`, autostart, bureau-snelkoppeling, thema's, agenda en touchkalibratie
  worden niet opnieuw ingesteld.

## Stap 1: op Windows, binnen PowerShell

**Gebruik je bestaande clone, niet opnieuw clonen:**

```powershell
cd "$env:USERPROFILE\Downloads\WakeSync-upload"

git pull --ff-only

Expand-Archive -Path "$env:USERPROFILE\Downloads\WakeSync-10.2.2-Alarm-en-Geluid.zip" -DestinationPath . -Force

py -3 tools\apply_wakesync_v1022.py --check
```

Alleen als de veiligheidscontrole slaagt:

```powershell
py -3 tools\apply_wakesync_v1022.py --apply

py -3 -m compileall -q src\wekker

git diff --check
git status --short
```

Daarna alleen gerichte softwarebestanden naar GitHub:

```powershell
git add pyproject.toml
git add src/wekker/__init__.py src/wekker/alarm/core.py
git add src/wekker/gui/app.py src/wekker/gui/premium.py src/wekker/gui/premium_render.py
git add src/wekker/hardware/audio.py src/wekker/api/server.py
git add tests/test_premium_render.py tests/test_premium_v102_visual.py tests/test_wakesync_v1022.py
git add tools/apply_wakesync_v1022.py tools/test_wakesync_alarm_audio.py
git add updates/v10_2_2 LEESMIJ-WAKESYNC-10.2.2.md docs/WAKE_SYNC_10_2_2.md

git diff --cached --stat
git commit -m "WakeSync 10.2.2 - alarm stoppen en USB audio"
git push origin main
```

**Bij een veiligheidsstop: niet forceren, geen `git reset`.** Stuur de foutmelding.

## Stap 2: op de Raspberry Pi (via SSH)

Sluit eerst de huidige WakeSync-app op het scherm. Haal de commit op:

```bash
cd ~/slim2/slim
git status --short
git pull --ff-only
source .venv/bin/activate
python3 -m pip install -e .
```

Test de luidspreker op een prettig volume:

```bash
python3 tools/test_wakesync_alarm_audio.py --seconds 3 --volume 65
```

Als je niets hoort, probeer gericht de USB-kaart (die bij jou als `Device` zichtbaar was):

```bash
python3 tools/test_wakesync_alarm_audio.py --device "plughw:CARD=Device,DEV=0" --seconds 3 --volume 65
```

De tool toont de gekozen uitgang, eventuele foutmelding en stopt vanzelf.
**Een test zonder technische fout is nog geen garantie dat het hoorbaar was.**

Als het alleen met `--device` werkt, leg de gekozen uitgang lokaal vast:

```bash
mkdir -p ~/.config/wakesync
printf '%s\n' 'plughw:CARD=Device,DEV=0' > ~/.config/wakesync/audio-device.txt
```

Dit is een lokaal bestand, **niet in GitHub**, en wordt bij de volgende
WakeSync-start automatisch gelezen. `WEKKER_AUDIO_DEVICE` in de omgeving heeft
voorrang op deze lokale keuze.

Start vervolgens de app met het al werkende commando:

```bash
wakesync
```

Test een alarm en controleer dat **Snooze** werkt en dat
**Alarm stoppen** meteen geluid én Snooze stopt.

## Technische opmerkingen

- De oude `dismiss(physical=False)` wordt nog steeds geweigerd; alleen een
  expliciete aanraakactie `dismiss(touchscreen=True)` of een fysieke knop kan
  stoppen. Daardoor is er geen onbedoelde versoepeling van oude API-aanroepen.
- De werkende ADS7846-kalibratie in `~/.config/labwc/rc.xml` wordt niet aangeraakt.
- Ook je MyX-feed, tokens, cache en privé-instellingen worden niet meegenomen.
- De installer gebruikt hashes van de geüploade broncode, houdt rekening met
  LF versus CRLF op Windows en maakt een byte-exacte back-up vóór het wijzigen.
- `--check` en `--apply` zijn herhaalbaar. Een afwijkende versie stopt zonder te
  overschrijven. Een herstelmanifest wordt afgedrukt na `--apply`.
- Lokaal zijn 91 gerichte regressietests geslaagd en is de touchscreenstop
  op een virtueel 800×480-scherm getest. De geluidsuitvoer zelf moet op je Pi
  worden gecontroleerd; de Pi-hardware is hier niet beschikbaar.
