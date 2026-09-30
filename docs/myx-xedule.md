# MyX / Xedule koppelen

De voorkeursmethode is de **MyX InternetCalendar Feed**. In WakeSync v8 gebeurt
de normale configuratie via de persoonlijke beheerpagina op
`https://veendomain.nl/klok/test2.pl`; de oude lokale webapp op poort 8080 is
geen onderdeel van de productstart.

## Feed uit MyX

MyX kan via **Mijn rooster → ⋮ → Feed** een agenda-abonnement aanbieden met
dit patroon:

```text
webcal://aventus.myx.nl/api/InternetCalendar/feed/<user-uuid>/<feed-uuid>
```

WakeSync valideert uitsluitend het officiële `aventus.myx.nl`-feedpad,
normaliseert `webcal://` lokaal naar `https://` en haalt de ICS-feed periodiek
op. Dezelfde feedlink kan de actuele agenda blijven leveren; er staat geen
specifieke kalenderdatum in de URL.

Een `blob:https://...`-URL uit een browserdownload is geen bruikbare permanente
feed en wordt geweigerd.

## Koppelen via veendomain.nl

1. Open de persoonlijke WakeSync-beheerpagina via de QR-code op het apparaat.
2. Log in met de persoonlijke WakeSync-inloggegevens.
3. Open MyX in een normale browser en ga naar **Mijn rooster**.
4. Kies de drie puntjes en daarna **Feed**.
5. Kopieer de `webcal://.../api/InternetCalendar/feed/.../...`-link.
6. Plak deze in de MyX/iCalendar-instelling en sla op.
7. `test2.pl` bewaart de nieuwe feed tijdelijk voor dat specifieke apparaat.
8. De Raspberry Pi haalt de feedconfiguratie op via zijn device-authenticatie,
   valideert en bewaart de feed lokaal.
9. Na succesvolle lokale opslag stuurt de Pi een ontvangstbevestiging
   (**ACK**) naar `test2.pl`; daarna wordt de tijdelijke feed-URL op de server
   verwijderd.

De feedlink functioneert als een geheim abonnementstoken en wordt daarom niet
als gewone cloudsetting teruggetoond.

## Lokale opslag

De feed wordt lokaal opgeslagen onder de applicatiedatamap, standaard:

```text
~/.local/share/aventus-wekker/myx-feed.json
```

De bestaande mapnaam blijft voorlopig behouden voor compatibiliteit met
bestaande installaties. Op Linux probeert WakeSync beperkte rechten (`0600`)
op het feedbestand te gebruiken.

## Synchronisatie en offline gebruik

Agenda-HTTP draait in v8 buiten de alarm-/GUI-thread. Een trage of geblokkeerde
MyX-request mag dus niet voorkomen dat de klok/touch reageert of een alarm
wordt getriggerd.

De lokale agendacache houdt afzonderlijk bij:

- laatste synchronisatiepoging;
- laatste geslaagde synchronisatie;
- welke dagen aantoonbaar zijn geladen;
- de laatste foutstatus.

Een mislukte netwerkpoging maakt oude data niet kunstmatig 'vers'. Bij een
offline herstart blijft de laatst bekende agenda beschikbaar.

## Beveiliging

- schoolwachtwoorden worden niet door WakeSync opgeslagen;
- feed-URLs en tokens horen niet in gewone instellingen of diagnose-export;
- alleen de bekende MyX-feedstructuur op `aventus.myx.nl` wordt geaccepteerd;
- `blob:`-, gewone HTTP- en vreemde domeinlinks worden geweigerd;
- cloudtransport gebruikt het apparaatkanaal; een feed wordt pas op de server
  verwijderd nadat de Pi de lokale ontvangst heeft bevestigd.

## Browser-SSO fallback

De oudere Chromium/SSO-code blijft voor compatibiliteit en ontwikkeling
aanwezig, maar is niet de aanbevolen normale productflow. De iCalendar-feed via
de persoonlijke beheerpagina is eenvoudiger en vereist geen blijvende lokale
webapp.
