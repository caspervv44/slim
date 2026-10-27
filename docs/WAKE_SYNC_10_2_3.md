# WakeSync 10.2.3 — technische notities

## Wat verandert

- `AlarmProfile.sound` bestond al en wordt per profiel bewaard via
  `Settings.to_dict()`, `Settings.update_from_dict()` en `apply_runtime_settings()`.
  Aan het schema is geen veld toegevoegd.
- `wekker.alarm.sounds` levert een centraal gedeelde catalogus (15 sleutels).
  De eerste vier bestaande sleutels zijn ongewijzigd: `beep`, `classic`, `soft`,
  `digital`. Oude onbekende klanken blijven geldig en spelen via de bestaande
  beep-fallback af; de keuze-interface biedt alleen ondersteunde sleutels.
- `wekker.hardware.tone_patterns` genereert 11 nieuwe melodieën als 16-bit
  mono PCM (22050 Hz); de oorspronkelijke 4 WAV-patronen zijn niet gewijzigd.
- `AplaySpeaker` en zijn USB/Pulse/ALSA-routekeuze zijn niet gewijzigd,
  behalve het oproepen van de nieuwe synthesizer.
- Premium gebruikt een apart 3×5-detailpaneel met twee acties per geluid:
  `sound-select` slaat het geluid op en `sound-preview` speelt tijdelijk af.
- De legacy Tkinterface krijgt dezelfde 15 keuzen.
- De preview stopt via een Tk-timer en bewaakt de actieve alarmstatus; hij
  onderbreekt nooit een inmiddels gestart echt alarm.
- `pyproject.toml` en `wekker.__version__` worden 10.2.3.
- `tools/test_wakesync_alarm_audio.py --sound <sleutel>` herkent nu 15 keuzen.

## Invarianten

- Geen wijziging aan autostart, desktop-entry, cloud-API, hardwarekalibratie,
  privéfeeds, alarmtrigger, snooze, touchstop of lampinstellingen.
- Geen extra Python-bibliotheken, netwerkverzoeken of gedownloade geluidsbestanden.
- De installer schrijft alleen naar expliciete codepaden na exacte SHA-checks
  met CRLF/LF-normalisatie en maakt een herstellende bron-back-up.

## Uitgevoerde controles

- 58 regressietests (10.2.2 + 10.2.3): geslaagd.
- 15 verschillende PCM/WAV-bestanden gecontroleerd op geluidsgolf,
  duur, clipgrens en volume=0.
- Premium-Tk-smoketest op virtueel 800×480 met alarm openen, selectie en
  persistente opslag: geslaagd.
- Alle vier premiumkleuren op 800×480 visueel gerenderd.
- Installer op gekopieerde 10.2.2-baseline: check, apply, idempotentie,
  restore en veiligheidsstop bij bronconflict: geslaagd.
- Nog niet uitgevoerd: echte hardwareproef van de 11 nieuwe klanken op
  de USB-speaker van de gebruiker.
