# WakeSync v8 — uitvoering van PLAN-VOOR-GOEDKEURING

Deze versie voert de aanbevolen eerste bouwscope van het plan uit:
**A1–A7 + B1–B6**, met een beperkte uitvoering van **C4** en de veilige
release-/updaterdelen van **C5**.

## A — betrouwbaarheid en installatie

| ID | Status in v8 | Opmerking |
|---|---|---|
| A1 | Geïmplementeerd | Profiel `waveshare-5-hdmi-ads7846`, detectie, backup, idempotente labwc-mapping, optionele bootconfig na expliciete profielbevestiging en verificatie na reboot. Op de bekende Pi, waar ADS7846 al wordt gedetecteerd, wordt bootconfig niet aangeraakt. |
| A2 | Geïmplementeerd | Updater werkt met staging, kopiebackup, operatiejournal, healthcheck en gerichte rollback. Foutinjectietests dekken backup, staging, journal, remove, copy, pip, health en restart. |
| A3 | Geïmplementeerd | `test2.pl` valideert sessie vóór save/password-formulierinhoud wordt verwerkt of teruggerenderd. |
| A4 | Geïmplementeerd | Agenda-ophalen en lokale feedverwerking lopen via een begrensde achtergrondworker. Alarm- en GUI-tick blijven vrij van netwerkrequests. |
| A5 | Geïmplementeerd | Agenda- en alarmruntime zijn atomair persistent. Snooze/dismiss overleven herstart. Gemiste alarmen hebben een herstelvenster van 10 minuten. Schema-migratie en corrupte bestanden zijn afgevangen. |
| A6 | Geïmplementeerd | Nieuwe instellingen worden eerst opgeslagen en daarna live toegepast; bij fout wordt de vorige geldige runtime hersteld. De updater accepteert nieuwe code pas na `python -m wekker healthcheck`. |
| A7 | Geïmplementeerd | Alarmstate/timers worden pas na geslaagde hardwaretransities gecommit; bij driverfout wordt de oude hardwaretoestand zo goed mogelijk hersteld en blijft retry mogelijk. |

### Vastgelegde A5-policy

- Een fysiek afgehandeld alarm wordt dezelfde kalenderdag niet opnieuw
  geactiveerd.
- Snooze bewaart zijn oorspronkelijke eindmoment over een herstart.
- Een gemist alarm wordt alleen binnen **10 minuten** alsnog geactiveerd.
  Daarna verschijnt een zichtbare melding.
- Een synthetisch gemist alarm door een foutieve systeemklok mag na een
  NTP-correctie terug vóór de echte alarmtijd worden hersteld.
- Een echte fysieke dismiss wordt door zo'n achterwaartse klokcorrectie
  niet ongedaan gemaakt.

## B — dagelijks zichtbare verbeteringen

| ID | Status in v8 | Opmerking |
|---|---|---|
| B1 | Geïmplementeerd | Vandaag: grote tijd links; volgende alarm/dag; rechts huidige of volgende les, tijd, docent en vast groot lokaal. |
| B2 | Geïmplementeerd | Hele dag is via paginering bereikbaar, met dagknoppen, huidige-lesmarkering, pauze/overlap en vaste ondernavigatie. |
| B3 | Geïmplementeerd | Alarm-/snoozeoverlay heeft prioriteit boven slaap, QR, instellingen en update. Snooze heeft een grote knop; stoppen blijft via de fysieke productknop. |
| B4 | Geïmplementeerd | `Nog niet geladen`, `Bijgewerkt om …` en `Eerder rooster getoond`; `Geen lessen` alleen voor een aantoonbaar geladen lege dag. |
| B5 | Geïmplementeerd | Instellingen zijn opgesplitst in Weergave, Online beheer, Software, Touchscreen & beeld en Diagnose voor 800×480. |
| B6 | Geïmplementeerd | Opslaan geeft zichtbare bevestiging/fout, QR-overlay blijft open, en Vandaag volgt middernacht zolang de gebruiker niet bewust een andere dag bekijkt. |

## C — bewust beperkt in v8

- **C1** school-/vakantieprofielen: later.
- **C2** wekken vanuit eerste les: later.
- **C3** echte lamp/speaker/knopdrivers: later, zodra de onderdelen en
  aansluitingen bevestigd zijn.
- **C4** beperkt uitgevoerd: appversie, laatste agenda-sync/poging, NTP,
  display/touch, backlight, cloud en updaterstatus plus veilige JSON-export.
  Device-key, wachtwoord en geheime feed-URL worden niet geëxporteerd.
- **C5** updater gebruikt standaard stabiele GitHub Releases, een vaste
  releaseversie, optionele SHA-256 en veilige installatiemomenten. Een checksum
  is alleen integriteitscontrole; release-attestation-verificatie is nog niet
  geïmplementeerd.
- **C6** afzonderlijke processen/watchdog: later.

Kernel-, volledige Raspberry Pi OS- en EEPROM-updates worden in v8 niet
automatisch geflasht.

## Fysieke validatie

De softwaretests zijn geautomatiseerd. De profielspecifieke boot-overlay kan
in deze ontwikkelomgeving niet op de echte Raspberry Pi worden bewezen. Op het
bekende apparaat is ADS7846 al door Linux gedetecteerd; daar hoort v8 alleen de
Wayland/labwc-outputmapping te controleren of corrigeren.
