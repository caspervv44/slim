# MyX / Xedule koppelen

De voorkeursmethode is nu de **MyX InternetCalendar Feed**. De configuratie
gebeurt via de webinterface van de wekker (`http://<pi-ip>:8080/`), niet via
een instellingenmenu op het ingebouwde touchscreen.

## Waarom de Feed beter is

MyX heeft in **Mijn rooster → ⋮ → Feed** een agenda-abonnement. Uit de
aangeleverde MyX-frontend blijkt dat MyX hiervoor een URL maakt met dit patroon:

```text
webcal://aventus.myx.nl/api/InternetCalendar/feed/<user-uuid>/<feed-uuid>
```

De wekker normaliseert `webcal://` lokaal naar `https://` en haalt de ICS-feed
periodiek op. Er staat **geen datum in de URL**: dezelfde feedlink wordt dus
steeds opnieuw gebruikt en MyX levert de actuele agenda-inhoud.

De `blob:https://aventus.myx.nl/<uuid>`-links die een browser bij handmatig
downloaden toont zijn iets anders. Een blob-URL is browserlokale tijdelijke
opslag. De UUID kan bij elke download veranderen en is na sluiten/verversen
niet bedoeld als permanente agenda-URL. De wekker accepteert blob-links daarom
bewust niet.

## Koppelen via de webinterface

1. Start de wekker/API op het lokale netwerk.
2. Open `http://<ip-van-de-pi>:8080/`.
3. Log in op de setup-pagina.
4. Open MyX in een normale browser en ga naar **Mijn rooster**.
5. Kies naast **Mijn rooster** de drie puntjes en daarna **Feed**.
6. Kopieer de `webcal://.../api/InternetCalendar/feed/.../...` link.
7. Plak de link in **MyX / Xedule → Feed koppelen**.
8. De wekker valideert uitsluitend `aventus.myx.nl`, bewaart de link lokaal en
   probeert direct een rooster-sync.

De feedlink is een capability/abonnementslink: behandel hem als geheim. De
webinterface toont de opgeslagen link daarom niet terug.

## Lokale opslag

De feed staat in:

```text
~/.local/share/aventus-wekker/myx-feed.json
```

Op Linux krijgt dit bestand modus `0600`. **MyX-koppeling verwijderen** wist
de feed, de eventuele oude Bearer-token en het speciale Chromium-profiel.

## Fallback: browser-SSO op het Pi-scherm

Als de Feed-link niet gekopieerd kan worden, blijft de eerdere browser-SSO als
fallback bestaan. Start die vanuit de **webinterface** via
**Alternatief: eenmalig inloggen op het Pi-scherm**. Chromium opent dan op de
Pi, de student logt in via de officiële Aventus/MyX-pagina en de wekker leest
het tijdelijke access-token lokaal uit de browserflow.

Een Bearer-token is tijdelijk en wordt nooit kunstmatig permanent gemaakt.
Een blijvend Chromium-profiel kan een bestaande SSO-sessie soms gebruiken om
een nieuw token te verkrijgen. Zodra de school opnieuw inloggen vereist, moet
de student opnieuw authenticeren.

## Synchronisatie

De Feed-koppeling heeft voorrang op een oude Bearer-token. De wekker haalt
standaard 21 dagen vooruit uit de feed, filtert de ICS lokaal en behoudt de
bestaande cache wanneer MyX of het netwerk tijdelijk niet bereikbaar is.

De oude environment-variabelen blijven alleen als development-fallback bestaan:

```bash
export WEKKER_MYX_BEARER_TOKEN='...'
export WEKKER_MYX_ATT_ID='...'
```

## Beveiliging

- schoolwachtwoorden worden niet door de wekker opgeslagen;
- Feed-URLs en tokens worden niet in gewone instellingen of logs geschreven;
- alleen `https://aventus.myx.nl/api/InternetCalendar/feed/<uuid>/<uuid>` wordt
  als Feed geaccepteerd;
- `blob:`-, HTTP- en vreemde domeinlinks worden geweigerd;
- ontkoppelen verwijdert lokale MyX-authenticatiegegevens.
