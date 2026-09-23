# Online instellingenserver (`test2.pl`)

Dit CGI-script hoort op:

`https://veendomain.nl/klok/test2.pl`

De Raspberry Pi registreert zichzelf de eerste keer automatisch. De server maakt dan:

- een willekeurige 256-bit wekker-ID voor de beheer-URL;
- een afzonderlijke 256-bit API-sleutel die alleen op de Pi wordt opgeslagen;
- gebruikersnaam `basis`;
- een willekeurig startwachtwoord van 16 tekens.

De menselijke beheerpagina vereist altijd de gebruikersnaam + het wachtwoord.
Wachtwoorden worden met PBKDF2-HMAC-SHA256 en een unieke salt opgeslagen.
De API gebruikt niet hetzelfde wachtwoord maar een aparte device key.

MyX-feedlinks, Bearer-tokens en andere accountgeheimen worden bewust niet naar
deze server gesynchroniseerd.

## Installeren op de webserver

1. Upload `test2.pl` naar `/klok/test2.pl`.
2. Maak het script uitvoerbaar:

   ```sh
   chmod 755 test2.pl
   ```

3. Zorg dat CGI/Perl voor `.pl` al werkt. Omdat `test.pl` op dezelfde server
   al werkt, is dat waarschijnlijk al ingesteld.
4. Gebruik bij voorkeur een opslagmap **buiten** de publieke webroot en geef
   de CGI-gebruiker daar schrijfrechten. Stel vervolgens in Apache/Plesk de
   environment variables in:

   ```text
   WEKKER_DATA_DIR=/home/<account>/private/aventus-wekker
   WEKKER_PUBLIC_URL=https://veendomain.nl/klok/test2.pl
   ```

   Als `WEKKER_DATA_DIR` niet is ingesteld, gebruikt het script
   `/klok/.clock-data`. Het script zet daar automatisch een `.htaccess` in die
   directe webtoegang weigert. Buiten de webroot blijft de veiligste keuze.

5. HTTPS moet ingeschakeld blijven. De sessiecookie heeft `Secure`,
   `HttpOnly` en `SameSite=Strict`.

## Schaalbaarheid

Iedere wekker krijgt een eigen JSON-bestand en een eigen file-lock. Daardoor
schrijven verschillende gebruikers niet in hetzelfde bestand en kunnen
honderden wekkers naast elkaar worden opgeslagen zonder één gedeeld JSON-bestand
dat bij iedere wijziging volledig wordt gelockt.

Voor zeer grote aantallen (duizenden/tien-duizenden apparaten) is een database
zoals PostgreSQL een logische volgende stap, maar voor honderden apparaten is
deze per-device opslag bewust eenvoudig gehouden.

## Back-up

Maak back-ups van `WEKKER_DATA_DIR`. Zonder die map blijven de fysieke wekkers
werken met hun lokale instellingen, maar bestaande online beheeraccounts zijn
dan niet meer beschikbaar.
