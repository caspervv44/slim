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

MyX-feedlinks, Bearer-tokens en andere accountgeheimen worden bewust niet naar
deze server gesynchroniseerd.

## Installeren op de webserver

1. Upload `test2.pl` naar `/klok/test2.pl`.
2. Maak het script uitvoerbaar:

   ```sh
   chmod 755 test2.pl
   ```

3. Gebruik bij voorkeur een opslagmap buiten de publieke webroot en geef de
   CGI-gebruiker daar schrijfrechten. Stel waar mogelijk deze variabelen in:

   ```text
   WEKKER_DATA_DIR=/home/<account>/private/wavesync
   WEKKER_PUBLIC_URL=https://veendomain.nl/klok/test2.pl
   ```

   Als `WEKKER_DATA_DIR` niet is ingesteld probeert het script eerst
   `.wavesync-data` naast het script en daarna `$HOME/.wavesync-data`.
   Het script controleert zelf of de map schrijfbaar is.

4. Controleer na upload in je browser:

   ```text
   https://veendomain.nl/klok/test2.pl?health=1
   ```

   Een werkende installatie geeft JSON terug met onder andere:

   ```json
   {"ok":true,"service":"wavesync","version":2,"storage_writable":true}
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
