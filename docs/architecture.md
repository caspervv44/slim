# WakeSync v8 — architectuur

## Hoofdregel

De alarmtijdlijn en Tkinter-eventloop mogen nooit afhankelijk zijn van
netwerk-I/O. `main.run_once()` doet daarom alleen snelle lokale acties:

```text
AlarmClock.tick()
DisplayManager.tick()
ButtonController.tick()
displaycontext bijwerken
resultaten achtergrondworker verwerken
nieuwe agenda/cloudtaken hoogstens inplannen
```

Agenda-HTTP en lokale MyX-feedverwerking draaien via de begrensde
`BackgroundWorker`. Er kan per sleutel maximaal één taak tegelijk pending zijn.

## Opslag

```text
wekker-settings.json
.wakesync-agenda-cache.json
.wakesync-alarm.json
.wekker-cloud.json
```

Alle JSON-hoofdopslag gebruikt atomische temp-file + `fsync` + `replace`.

### Agenda

`AgendaCache` bewaart apart:

- laatste poging;
- laatste geslaagde synchronisatie;
- foutstatus;
- aantoonbaar geladen dagen;
- alle gecachte lessen per dag.

Een mislukte poging verandert de laatste geslaagde tijd niet en wist oude
lessen niet.

### Alarm

`AlarmRuntimeStore` bewaart:

- state;
- `ringing_since`;
- `snooze_until`;
- laatste triggerdatum;
- dismissdatum;
- zichtbare gemist-melding.

Beleid v8:

- dezelfde dag opnieuw starten na dismiss: **nee**;
- snooze na herstart: oorspronkelijke eindtijd blijft gelden;
- ringing/snooze wordt maximaal 10 minuten laat hersteld;
- daarna volgt een zichtbare melding in plaats van een urenlaat alarm;
- tijdzone/DST komt uit timezone-aware `Clock`/`zoneinfo`.

## Alarmtransacties

Een transition bestaat uit twee fasen:

1. benodigde speaker/lampactie uitvoeren;
2. pas na succes state en timers committen en persistent opslaan.

Faalt stap 1, dan probeert de core de oude hardwaretoestand te herstellen en
blijft de logische toestand retrybaar.

## Instellingentransactie

`apply_runtime_settings()`:

1. valideert/bouwt een eventuele nieuwe provider;
2. schrijft de nieuwe settings atomair;
3. past core/display/button/clock/provider live toe;
4. probeert bij runtimefout de oude geldige configuratie te herstellen.

Een opslagfout vindt plaats vóór runtime-mutatie.

## GUI 800×480

- hoofdscherm: tijd/alarm links, huidige of volgende les + lokaal rechts;
- agenda: volledige dag via 4 regels per pagina, vaste ondernavigatie;
- alarmoverlay: hoogste UI-prioriteit;
- instellingen per onderwerp;
- QR-overlay blijft open tijdens normale refreshes;
- slaapoverlay wordt door alarm direct gesloten.

## Touch/installatie

`touch_setup.py` bevat één expliciet ondersteund profiel:
`waveshare-5-hdmi-ads7846`.

Als ADS7846 al bestaat, wordt bootconfig niet gewijzigd; alleen de
Wayland/labwc-outputmapping wordt veilig en idempotent gecorrigeerd. Als de
driver ontbreekt, is expliciete profielbevestiging vereist voordat WakeSync
het gemarkeerde bootconfigblok toevoegt.

## Cloud

De Pi pollt `test2.pl` via HTTPS. Remote settings worden pas als gesynchroniseerd
ge-ACKt nadat de Pi ze lokaal heeft toegepast. MyX-feedlinks worden tijdelijk
op de server bewaard, lokaal opgeslagen en daarna met ACK verwijderd.

`test2.pl` valideert de websessie vóór de save/password-foutpagina toegang kan
krijgen tot apparaatgegevens.

## Updater

Productiekanaal = stabiele GitHub Release. Installatie gebruikt:

```text
download → veilige extractie → backup/staging → operatiejournal
→ vervangen → pip install → healthcheck → restart
                              ↘ fout: gerichte rollback
```

De GUI weigert een update tijdens ringing/snooze en vlak voor het volgende
alarm.

## Nog niet in v8

- echte speaker/lamp/GPIO-drivers;
- lesafhankelijke wektijd;
- vakantie-/schooldagprofielen;
- aparte alarmdaemon/watchdog;
- automatische kernel/OS/EEPROM-firmwareflash.
