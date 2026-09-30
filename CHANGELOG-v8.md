# WakeSync v8.0.0

## Betrouwbaarheid

- A1: ondersteund Waveshare 5-inch/ADS7846-profiel met detectie, backup,
  idempotente labwc-mapping, optionele bootconfig en post-rebootcontrole.
- A2: updaterbackup/staging + operatiejournal + gerichte rollback.
- A3: `test2.pl` eist een geldige sessie vóór save/password-foutpagina's.
- A4: agenda- en feedwerk uit de alarm-/GUI-thread.
- A5: persistente agenda- en alarmruntimecache.
- A6: instellingentransactie + updater-healthcheck.
- A7: alarmstate commit pas na geslaagde hardwareactie.

## Interface

- B1: Vandaag-scherm met huidige/volgende les en groot lokaal.
- B2: volledige dagagenda met paginering, current/overlap/pauze.
- B3: prioriteits-alarm/snoozescherm.
- B4: eerlijke roosterstatus.
- B5: instellingen per onderwerp.
- B6: consistente save-foutfeedback, QR-overlay blijft open en Vandaag volgt
  middernacht.

## Diagnose/release

- beperkte C4-diagnose: versie, agenda, NTP, cloud, touch/output, backlight en
  updaterstatus, zonder geheimen;
- stabiele GitHub Release als standaard updatekanaal;
- geen update tijdens ringing/snooze of vlak voor het alarm.

## Niet in deze release

School-/vakantieprofielen, wekken vanuit eerste les, echte speaker/lampdrivers,
watchdog/proces-splitsing en OS/kernel/EEPROM-flashupdates.
