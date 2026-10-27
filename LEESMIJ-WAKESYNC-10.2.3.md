# WakeSync 10.2.3 — vijftien alarmgeluiden per alarm

Deze update bouwt voort op de werkende WakeSync **10.2.2** op de Raspberry Pi.
De gekalibreerde ADS7846-touchscreeninstellingen, C9-logo's, thema's, MyX-koppeling,
USB-audio-uitgang, bureaubladstart en terminalcommando worden niet aangepast.

## Wat verandert?

- 15 verschillende, lokaal gegenereerde WAV-klanken (de oorspronkelijke 4 blijven ongewijzigd).
- Kies een eigen geluid voor **ieder alarmprofiel**.
- In het premium-alarmdetailscherm: tik op **Geluid** om de 15 keuzen te openen.
- Tik op de **naam** om het geluid op te slaan; tik op **▶** om eerst te luisteren.
- Gebruik **‹ Terug** om terug te gaan naar het alarmdetailscherm.
- Ook de oudere Tk-weergave krijgt een geluidskiezer.
- De bestaande audiohardware, snooze- en stopbediening blijven gelijk.

Geluiden: Basisbeep, Klassiek, Zacht, Digitaal, Ochtendglans, Klokkenspel,
Piano, Marimba, Klokken, Radar, Hartslag, Arcade, Sterren, Melodie en Energiek.
Dit zijn **synthetische melodieën en tonen**, geen gedownloade MP3-nummers.
Ze worden zonder internet en zonder extra Python-afhankelijkheden als WAV afgespeeld.

## A. Windows: uploaden naar GitHub

Open PowerShell op de pc, niet via SSH.

```powershell
cd "$env:USERPROFILE\Downloads\WakeSync-upload"
git status --short
git pull --ff-only
```

Download `WakeSync-10.2.3-Alarmgeluiden.zip` in Downloads en pak uit:

```powershell
Expand-Archive -Path "$env:USERPROFILE\Downloads\WakeSync-10.2.3-Alarmgeluiden.zip" -DestinationPath . -Force

py -3 tools\apply_wakesync_v1023.py --check
```

**Alleen als `--check` slaagt**, toepassen:

```powershell
py -3 tools\apply_wakesync_v1023.py --apply
py -3 -m compileall -q src\wekker
git diff --check
git status --short
```

De `--apply`-stap maakt een back-up buiten de repository en geeft het
exacte pad van het herstelmanifest. Als een bronbestand afwijkt,
stopt de installer voordat er iets wordt gewijzigd. Forceer dit niet.

Commit uitsluitend de softwarebestanden:

```powershell
git add pyproject.toml src/wekker/__init__.py
git add src/wekker/alarm/sounds.py
git add src/wekker/gui/app.py src/wekker/gui/premium.py src/wekker/gui/premium_render.py
git add src/wekker/hardware/audio.py src/wekker/hardware/tone_patterns.py
git add tools/test_wakesync_alarm_audio.py tools/apply_wakesync_v1023.py
git add tests/test_wakesync_v1023.py updates/v10_2_3
git add LEESMIJ-WAKESYNC-10.2.3.md docs/WAKE_SYNC_10_2_3.md
git diff --cached --stat
git commit -m "WakeSync 10.2.3 - vijftien alarmgeluiden per alarm"
git push origin main
```

Bij een veiligheidsstop of onverwachte fout: NIET pushen. Stuur de melding door.

## B. Raspberry Pi: bijwerken

Open SSH, sluit eerst de lopende WakeSync GUI en voer uit:

```bash
cd ~/slim2/slim
git status --short
git pull --ff-only
source .venv/bin/activate
python3 -m pip install -e .
python3 -m pytest -q tests/test_wakesync_v1023.py
```

Geluidstest via dezelfde USB-audio-uitgang:

```bash
python3 tools/test_wakesync_alarm_audio.py --sound marimba --seconds 3 --volume 65
```

Start de GUI vanaf het scherm of via het bestaande commando:

```bash
wakesync
```

Ga naar **Alarm**, open een alarm, tik op **Geluid** en kies of beluister
een van de vijftien opties. Herhaal voor een tweede alarm als je wilt.

Je hoeft het bureaubladicoon of autostart **niet opnieuw te installeren**.

## Veiligheid en bekende grenzen

- De update schrijft niet in `~/.config/labwc/rc.xml`, `/boot/firmware/config.txt`
  of je persoonlijke WakeSync-instellingen.
- Het instellingenformaat had al per alarm een `sound`-veld: geen gegevensmigratie.
- Er worden geen extra hardwareonderdelen, bestanden met muziek of GPIO-pinnen gebruikt.
- Je bestaande audiokeuze blijft leidend; `aplay` speelt de nieuw gegenereerde WAV's.
- Voorbeeldknoppen stoppen niet per ongeluk een echt afgaand alarm.
- Audioklanken zijn lokaal synthetisch gegenereerd en getest op geldig PCM/WAV.
  Het uiteindelijke geluid door jouw USB-speaker moet op de Pi worden gehoord.
- Een onverwachte wijziging in bronbestanden veroorzaakt een veiligheidsstop.
- Een herstelmanifest kan gebruikt worden met:
  `py -3 tools\apply_wakesync_v1023.py --restore "VOLLEDIG_PAD_NAAR_MANIFEST.json"`
