# WakeSync Premium v10.2.0 — vier goedgekeurde thema's

Deze ZIP is een **updatepakket bovenop de openbare WakeSync-broncode 10.1.1**,
niet een losstaande vervanging van de bestaande repository.

## Inhoud

- **Midnight Glass** (`midnight`), **Aurora Slate** (`ocean`),
  **Light Executive** (`light`), **Ember Noir** (`amber`).
- Vandaag, Agenda, Alarm, Instellingen in één grafische stijl.
- Thema-afhankelijke **slaapschermen**, met de originele C9-logobron
  uit de bestaande repository. De **P-toets** opent het sleepscreen.
- **Vandaag** heeft geen inspirerende quotes meer. **Temperatuur** toont `☀ --`
  totdat een sensor wordt aangesloten.
- **Weergave-instellingen** en **alarmdetails** zijn nieuwe schermen met
  touchknoppen. De bestaande **alarm-aanmaak** (datum + 360° dial) blijft werken
  met een gethematiseerde achtergrond.
- Minder zichtbare **flitsen bij tabwissels**: het permanente Canvas blijft leven
  en de nieuwe afbeelding wordt atomair omgeschakeld. Alleen gewijzigde
  schermdata en minuten leiden tot een render.
- **ALSA-geluidsdriver** voor echte USB-/HDMI-geluidsuitvoer van de Raspberry Pi,
  met `MockSpeaker` als veilige fallback op laptops en zonder `aplay`.
- MyX-feed wordt **eenmalig privé** lokaal opgeslagen; geen URL/token in Git.

De bestaande alarmkern, snooze, datumalarmen, agenda, updatefunctie en het
goedgekeurde C9-logo worden niet gewijzigd. `deploy/cloud/test2.pl` en alle
andere webserverbestanden blijven ongewijzigd.

## Op je computer — ZIP verwerken en GitHub pushen

1. Werk in een schone clone van `https://github.com/caspervv44/slim`
   op versie 10.1.1 en zorg dat je vorige premium wijzigingen gepusht zijn.
2. Pak de inhoud van de ZIP **in de root van `slim`** uit. Sta overschrijven
   van de twee premium-GUI-bestanden toe, maar vervang geen persoonlijke JSON.
3. Voer in die repository uit:

   ```bash
   python3 tools/apply_premium_v102.py
   python3 -m compileall -q src tests tools
   python3 -m pytest -q
   ```

4. Controleer `git diff` en `git status`. Commit en push de relevante code,
   grafische assets, tests, instructies en de door de installer gewijzigde
   `main.py`, `__init__.py` en `pyproject.toml`.

   **Commit nooit** `wekker-settings.json`, `.wakesync-*.json`,
   `myx-feed.json`, een privé-ICS, tokens of wachtwoorden.

De installer weigert onbekende versies en gewijzigde startpunten, in plaats
van bestaande code blind te overschrijven. Hij schrijft de originele
drie bronbestanden in `~/.local/share/wakesync-premium-v102/` buiten Git.

## Op de Raspberry Pi — pull en eerste gebruik

```bash
cd ~/slim
git pull --ff-only
source .venv/bin/activate
python3 -m pip install -e ".[dev]"
python3 -m compileall -q src tests tools
python3 -m pytest -q
python3 -m wekker healthcheck
```

### MyX alleen voor de eerste keer

```bash
python3 tools/configure_private_myx.py
python3 tools/configure_private_myx.py --check
python3 -m wekker inspect-myx --days 7
```

Plak bij de eerste opdracht je eigen `webcal://`-link **als verborgen invoer**.
Het script zet deze automatisch om naar HTTPS en gebruikt de bestaande
`MyXFeedStore` (lokale rechten 0600). In `wekker-settings.json` staat alleen
`agenda.provider = "myx"`; **de echte link hoort nooit in GitHub**.

Voer deze opdracht uit onder dezelfde Linux-gebruiker als de wekkerapp.
Hierna wordt de agendacache weer automatisch bijgewerkt volgens de bestaande
MyX-sync. Een verbinding met MyX is nodig voor de **eerste** echte sync;
offline bewaart de bestaande cache eerdere lessen.

### GUI testen

```bash
# Eerst rustig testen, zonder echte speaker:
WEKKER_AUDIO=mock python3 -m wekker gui --window

# Echte luidspreker aangesloten:
python3 -m wekker gui --window
```

Bij problemen kun je de vorige Git-commit terugzetten. De persoonlijke
feed en agendacache blijven lokaal staan, buiten de code-repository.

## Geluid instellen

De Pi 5 heeft geen standaard 3,5mm analoge audio-uitgang.
Sluit een geschikte USB-/HDMI-speaker aan en controleer de ALSA-uitgang:

```bash
sudo apt install alsa-utils
aplay -l
```

WakeSync gebruikt op de Pi automatisch `aplay` wanneer dat beschikbaar is.
Een andere uitvoer selecteer je met `WEKKER_AUDIO_DEVICE`, bijvoorbeeld
een op jouw Pi aangetroffen ALSA-device uit `aplay -L` (geen device gokken):

```bash
WEKKER_AUDIO=alsa WEKKER_AUDIO_DEVICE=<jouw-ALSA-device> python3 -m wekker gui --window
```

Voor een korte test zonder wekkeralarm:

```bash
python3 tools/test_audio.py --seconds 2 --volume 40
```

**Test fysiek vóór je erop vertrouwt om wakker te worden.**
Snooze en stoppen roepen de bestaande `Speaker.stop()` aan. Als ALSA niet
kan starten, logt de driver een fout; een daadwerkelijke geluidscontrole
is dus noodzakelijk.

## Bediening en bekende beperkingen

- Op het hoofdscherm: **Vandaag / Agenda / Alarm / Instellingen**.
- Tik op **Alarm** en tik op de naam/tijd van een bestaand alarm voor
  de nieuwe premium-alarmdetails; hier kun je ook het geluid testen.
- Tik op **Instellingen → Thema**, of de andere weergavetegels,
  om de premium-weergave-instellingen te openen.
- Tik in weergave-instellingen op **Sleepscreen testen** of druk op **P**
  vanuit het hoofdscherm. Tik of druk een andere toets om terug te gaan.
- Andere bestaande diagnostiek-/cloud-overlays behouden hun huidige
  functionaliteit en hun themakleuren. Er wordt **niets aan de webpagina
  `test2.pl` aangepast**.
- Het slaapscherm heeft momenteel een **statische premium illustratie**,
  zodat de Raspberry Pi geen zware continue renderloop draait. De kloktijd
  zelf wordt wel live bijgewerkt. De bestaande selectie van slaapeffecten
  en gloedsterkte blijft bewaard.
- De grafische testvoorbeelden bevatten **fictieve lesgegevens**, niet jouw
  persoonlijke MyX-feed.
- Een Pi met een aangesloten touchscreen/speaker is in deze omgeving niet
  beschikbaar. Daarom zijn touchreactie, werkelijke audio en prestaties
  nog **niet fysiek getest**.

## Herstel

De veiligste weg is `git revert` van de v10.2-commit, gevolgd door opnieuw
`pip install -e ".[dev]"`. De herstelhelper:

```bash
python3 tools/revert_premium_v102.py
```

zet alleen de automatisch gewijzigde bestaande bronbestanden terug, en weigert
te overschrijven als die na installatie handmatig zijn veranderd. De overige
premium-bestanden kun je via Git terugzetten.
