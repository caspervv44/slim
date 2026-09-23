# WaveSync online instellingenserver (`test2.pl`)

Dit CGI-script hoort op:

`https://veendomain.nl/klok/test2.pl`

De Raspberry Pi maakt bij de eerste start lokaal een cryptografisch willekeurige
256-bit device-ID, een aparte 256-bit device key en een startwachtwoord van
16 tekens aan. Daardoor kan de QR-code direct op het scherm verschijnen, zelfs
als de webserver tijdelijk niet bereikbaar is. Zodra de verbinding beschikbaar
is registreert de Pi deze identiteit op de server.

De menselijke beheerpagina gebruikt:

- gebruikersnaam `basis`;
- het willekeurige startwachtwoord van 16 tekens;
- een niet-oplopende 256-bit beheer-ID in de URL.

Wachtwoorden worden op de server alleen gehasht opgeslagen met
PBKDF2-HMAC-SHA256 en een unieke salt. De Raspberry Pi gebruikt voor API-calls
niet het gebruikerswachtwoord maar de aparte device key.

Een MyX-feedlink kan via de beheerpagina worden ingesteld. De server bewaart
die URL alleen tijdelijk in het apparaatrecord. De gekoppelde Pi haalt hem op
met de aparte device key en bevestigt daarna de ontvangst; vervolgens wordt de
feed-URL uit de serveropslag verwijderd. Bearer-tokens en schoolwachtwoorden
worden nooit via deze server opgeslagen.

## Installeren op de webserver

1. Upload `test2.pl` naar `/klok/test2.pl`.
2. Deze installatie draait op Windows/WAMP met Perl uit:

   ```text
   C:/Perl64/bin/perl.exe
   ```

   Dat pad staat daarom bewust in de eerste regel van `test2.pl`.

3. De bekende werkende standaardopslag is:

   ```text
   C:/wamp64/www/veendomain/klok/data/wavesync
   ```

   `WEKKER_DATA_DIR` kan dit overschrijven. Het script maakt een `.htaccess`
   aan om directe HTTP-toegang tot deze data te blokkeren. Nog beter is een
   private map buiten de webroot als WAMP daar schrijfrechten heeft.

4. Controleer na upload in je browser:

   ```text
   https://veendomain.nl/klok/test2.pl?health=1
   ```

   Een werkende installatie geeft JSON terug met onder andere:

   ```json
   {"ok":true,"service":"wavesync","version":5,"storage_writable":true,"storage_backend":"file-per-device"}
   ```

5. HTTPS moet ingeschakeld blijven. De sessiecookie gebruikt `Secure`,
   `HttpOnly` en `SameSite=Strict`.

## Diagnose vanaf de Raspberry Pi

```bash
curl -i 'https://veendomain.nl/klok/test2.pl?health=1'
```

Als dit geen HTTP 200 met JSON geeft, controleer dan de CGI error-log en de
schrijfrechten van `WEKKER_DATA_DIR`.

## Schaalbaarheid

Iedere WaveSync krijgt een eigen JSON-bestand en file-lock. Daardoor kunnen
honderden apparaten onafhankelijk synchroniseren zonder één groot gedeeld
bestand te locken. De device-ID's zijn willekeurig en niet afleidbaar van
andere gebruikers.

Voor veel grotere installaties is een database zoals PostgreSQL een logische
volgende stap.

## Back-up

Maak back-ups van `WEKKER_DATA_DIR`. Zonder die map blijven fysieke WaveSyncs
werken met hun lokale instellingen, maar bestaande online beheeraccounts gaan
verloren.
