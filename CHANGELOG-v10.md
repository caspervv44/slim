# WakeSync v10.0.0

## Branding
- C9-logo opnieuw opgebouwd als hoog-resolutie transparante PNG voor het 800×480-scherm.
- Logo-schaal gebruikt hoogwaardige LANCZOS-resampling om rafels en losse witte pixels te voorkomen.
- Nieuwe branding wordt gebruikt in splashscreen, GUI, slaapmodus en `test2.pl`.

## Slaapmodus
- Bestaande effecten blijven: Uit, Zachte gloed, Pulserend en Aurora.
- Nieuw effect **Liquid Motion**: geanimeerde vloeiende neonbanden in blauw, cyan, paars/magenta en een warme accentkleur.
- Gloedintensiteit blijft instelbaar.
- Animatie gebruikt lichte Canvas-vormen zodat de Raspberry Pi 5 niet per frame grote afbeeldingen hoeft te genereren.

## Alarm
- Alarmtab opnieuw ontworpen rond meerdere alarmen.
- Linkerpaneel begint met een grote **+**.
- Nieuwe wekker instellen gebeurt stap voor stap: eerst uur op een 360°-dial, daarna minuten.
- Alarmkaart toont Vandaag/Morgen, tijd en een grijs/blauw aan/uit-schuifje.
- Rechterconfiguratie blijft leeg totdat een bestaand alarm wordt geselecteerd.
- Per alarm: snooze, volume, speaker, lamp, lampsterkte/effect, ramp-up en verwijderen.
- Legacy één-alarminstellingen worden automatisch gemigreerd naar het nieuwe profielmodel.

## Agenda / MyX
- Dynamische GUI-bug opgelost: als een lokaal pas na achtergrond-sync beschikbaar kwam, werd de agendarij eerder niet opnieuw opgebouwd.
- `LOCATION:-`, `LOCATION:—` en andere placeholders worden niet meer als lokaal behandeld.
- Lokaalextractie uitgebreid naar `DESCRIPTION`, `RESOURCES`, `X-ALT-DESC`, `COMMENT`, vendorvelden en iCalendar-propertyparameters zoals `ATTENDEE;CUTYPE=ROOM;CN=...`.
- URL-/HTML-gecodeerde lokaaltekst wordt opgeschoond.
- Als de feed echt geen lokaal bevat, verbergt WakeSync het lokaalveld volledig.
- Nieuwe veilige CLI `python -m wekker inspect-myx --days 21` controleert de echte gekoppelde feed zonder geheime URL te tonen.

## Online beheer
- `test2.pl` naar schema/healthversie 10.
- Hoog-resolutie C9-logo ingebed.
- `Liquid Motion` online instelbaar.
- API accepteert het nieuwe `alarm.alarms`-profielmodel.
- Webformulier blijft compatibel door de primaire alarmvelden te spiegelen naar het eerste alarmprofiel.
- Mobiele en desktop-tabs blijven behouden.

## Tijd
- WakeSync blijft de lokale Raspberry Pi-systeemtijd gebruiken; wifi is niet nodig om de klok of alarmberekening door te laten lopen.
- Bij volledig spanningsverlies is behoud van absolute tijd afhankelijk van de Raspberry Pi 5-RTC en de gekozen RTC-voeding/batterij.

## Touch
- Geen automatische touch-check of touch-reparatie in de productsoftware.
