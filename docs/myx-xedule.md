# MyX / Xedule koppelen op de Raspberry Pi

De wekker gebruikt de officiële MyX/Aventus-login in Chromium. Een student hoeft
geen Bearer-token te zoeken, kopiëren of in een instellingenbestand te plakken.

## Gebruikersflow

1. Open op het 800×480-scherm **Instellingen** via het tandwiel.
2. Druk op **MyX koppelen**.
3. De wekkerinterface verdwijnt tijdelijk en Chromium opent
   `https://aventus.myx.nl/`.
4. De student logt in via de normale Aventus/MyX/SSO-pagina.
5. Na succesvolle login leest de wekker lokaal het tijdelijke MyX access-token
   uit de MyX-browserflow. Het schoolwachtwoord wordt niet door de wekker
   gelezen of opgeslagen.
6. Chromium sluit en de wekkerinterface komt terug. MyX is nu de
   agenda-provider.

De lokale setup-webpagina biedt dezelfde knop. Die knop start de login op het
**ingebouwde scherm van de Raspberry Pi**, niet op de telefoon die de
setup-pagina eventueel opent.

## Waarom de student niet elke dag hoeft in te loggen

Een MyX access-token is tijdelijk. De wekker probeert dat token niet permanent
te maken. In plaats daarvan gebruikt Chromium een apart, blijvend profiel:

```text
~/.local/share/aventus-wekker/myx-browser/
```

Cookies en browseropslag die MyX/SSO zelf gebruikt blijven daardoor over een
herstart van de wekker/Pi heen bewaard. Wanneer het access-token minder dan
15 minuten geldig is, probeert de wekker een korte **headless Chromium**-sessie
met hetzelfde profiel. MyX kan dan via zijn eigen browserlogica de bestaande
sessie vernieuwen. De wekker leest het nieuwe access-token en sluit de
headless browser weer.

Als Aventus/Microsoft/MyX de SSO-sessie zelf laat verlopen, kan de wekker dat
niet en hoort hij dat ook niet te omzeilen. De instellingen tonen dan
**Opnieuw inloggen bij MyX**. Eén normale login maakt de koppeling opnieuw
bruikbaar.

De exacte levensduur van de SSO-sessie wordt door de school/identity-provider
bepaald en kan dus niet door dit project worden gegarandeerd.

## Lokale opslag

Het huidige access-token wordt opgeslagen in:

```text
~/.local/share/aventus-wekker/myx-auth.json
```

Op Linux krijgt het bestand modus `0600`; de map krijgt `0700`. De JWT zelf
wordt nooit op het scherm of in normale logs getoond.

Dit beschermt tegen per ongeluk meelezen door andere Unix-gebruikers, maar het
is geen bescherming tegen iemand die fysiek de SD-kaart kan uitlezen. Voor een
productieapparaat is versleutelde opslag/full-disk-encryptie een aparte
beveiligingsstap.

**MyX ontkoppelen** verwijdert zowel het tokenbestand als het speciale
Chromium-profiel. Daardoor kan een volgende student niet automatisch verder
met de SSO-sessie van de vorige student.

## Raspberry Pi-vereisten

Raspberry Pi OS moet Chromium en tkinter hebben:

```bash
sudo apt update
sudo apt install -y chromium python3-tk
```

Controleer:

```bash
chromium --version
python3 -c "import tkinter; print('tkinter ok')"
```

Als Chromium onder een afwijkende naam/pad staat, kan voor development worden
ingesteld:

```bash
export WEKKER_CHROMIUM_BIN=/pad/naar/chromium
```

## Starten

Vanuit de repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
python -m wekker gui
```

Voor testen in een normaal venster:

```bash
python -m wekker gui --window
```

## Wat technisch wordt onderschept

Er wordt geen HTTPS-verkeer ontsleuteld en er wordt geen wachtwoord
onderschept. Chromium wordt gestart met een DevTools-poort die uitsluitend op
`127.0.0.1` luistert. De wekker kijkt naar:

- de officiële MyX-terugkeer-URL met een `token`-queryparameter; en
- MyX API-requests in diezelfde Chromium-sessie die een authorization-token
  gebruiken.

Het DevTools-proces wordt gesloten zodra de login/tokenvernieuwing klaar is.

De JWT-payload wordt alleen lokaal gelezen voor `exp` (vervaltijd) en `atnId`
(MyX attendee-id). De handtekening wordt niet door de wekker zelf gebruikt als
identiteitsbewijs: het token is verkregen uit de HTTPS-browserflow van MyX en
wordt vervolgens door de MyX API zelf geverifieerd.

## Agenda synchroniseren

`MyXAgendaProvider` gebruikt het actuele token en de `atnId` uit de koppeling.
De bestaande agenda-cache blijft behouden bij netwerk- of authenticatiefouten.
De standaard synchronisatiehorizon is 21 dagen.

Voor oudere development-installaties blijven de environment variables als
fallback ondersteund:

```bash
export WEKKER_MYX_BEARER_TOKEN='...'
export WEKKER_MYX_ATT_ID='...'
```

Een student hoeft deze fallback niet te gebruiken.

## Problemen oplossen

### "Chromium is niet gevonden"

Installeer `chromium` of zet `WEKKER_CHROMIUM_BIN`.

### Na login komt de wekker niet terug

Wacht enkele seconden; de browser blijft kort open zodat MyX zijn sessie naar
het blijvende profiel kan schrijven. Als Chromium handmatig wordt gesloten
vóór de koppeling is afgerond, toont de wekker een fout en kan **MyX koppelen**
opnieuw worden gekozen.

### Iedere keer opnieuw inloggen

Controleer of deze map blijft bestaan en schrijfbaar is voor de gebruiker die
de wekker-service draait:

```bash
ls -ld ~/.local/share/aventus-wekker
ls -ld ~/.local/share/aventus-wekker/myx-browser
```

Start GUI en achtergrondservice altijd als dezelfde Linux-gebruiker. Anders
kijken ze naar verschillende Chromium-profielen.

### MyX vraagt na een tijd toch opnieuw om schoollogin

Dat is normaal wanneer de SSO-sessie door de school is verlopen of ingetrokken.
De wekker bewaart geen schoolwachtwoord en probeert dit beleid niet te omzeilen.
Gebruik **Opnieuw inloggen**.
