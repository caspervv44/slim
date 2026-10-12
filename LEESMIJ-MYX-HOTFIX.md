# WakeSync 10.2 — MyX/iCalendar synchronisatiehotfix

Deze patch vervangt **alleen** `tools/configure_private_myx.py` en voegt
regressietests toe. De interface, alarmen, cloudpagina en thema's blijven ongewijzigd.
Dit is **geen nieuwe volledige WakeSync-versie**.

## Wat is opgelost?

De originele helper meldde direct "Gelukt" nadat de privélink en provider op schijf
waren gezet, zonder de ICS op te halen of de agendacache te vullen. De verbeterde
helper doet nu bij een nieuwe koppeling een **echte synchronisatie**. Voor een
bestaande koppeling volstaat `--refresh`: de link blijft geheim en hoeft niet
opnieuw te worden geplakt.

De helper:
- gebruikt standaard `wekker-settings.json` **naast het script/de repository**
  in plaats van de toevallige terminalmap;
- meldt het exacte instellingenbestand en cachepad;
- zet `agenda.provider` op `myx` als een bestaande feed is opgeslagen;
- zet automatische sync op 15 minuten als die was uitgeschakeld;
- synchroniseert het bestaande MyX-ICS-abonnement direct naar de persistente cache;
- meldt **eerlijk** of de sync lukte, of er nul lessen zijn of welke fout optrad;
- toont geen feedlinks, tokens of volledige roosterinhoud;
- laat de andere instellingen, bestaande alarmen en persoonlijke JSON ongemoeid;
- stopt veilig zonder instellingen te vervangen als een onleesbaar of verkeerd
  instellingenbestand aanwezig is.

## Updaten in jouw GitHub → Raspberry Pi-werkwijze

Pak dit ZIP-pakket uit over de **hoofdmap van je lokale `slim`-repository**.
Commit de twee codebestanden en deze documentatie, en push naar GitHub.
Commit geen persoonlijke instellingenbestanden of de MyX-feed.

Op de Raspberry Pi, **in jouw huidige map**:

```bash
cd ~/slim2/slim
git pull --ff-only
source .venv/bin/activate
```

Sluit WakeSync volledig af voordat je handmatig synchroniseert.

De feed is al privé opgeslagen; **NIET nogmaals invoeren**:

```bash
python3 tools/configure_private_myx.py --refresh
python3 tools/configure_private_myx.py --check
```

Verwacht bij een werkende MyX-feed:

```text
Agendaprovider ingesteld op MyX.  # alleen als die voorheen niet op MyX stond
Synchronisatie: GELUKT
Gevulde kalenderdagen: 21
Lessen vandaag: <aantal>
Lessen komende 21 dagen: <aantal>
```

Een succesvolle HTTPS/ICS-aanvraag kan terecht 0 lessen geven (bijv. vakantie,
verkeerde gekoppelde kalender, of geen toekomstige afspraken). Daarvoor wordt
een aparte waarschuwing getoond.

Start vervolgens de GUI met exact hetzelfde instellingenbestand:

```bash
python3 -m wekker gui --settings "$PWD/wekker-settings.json"
```

Als een systemd-service jouw GUI start, controleer dan dat die **dezelfde
Linux-gebruiker, werkmap en instellingenpad** gebruikt. De privélink staat in
`~/.local/share/aventus-wekker/` van die gebruiker. De agendacache staat
naast het instellingenbestand: `.wakesync-agenda-cache.json`.

### Waarom dit nodig is

De oude versie schreef de link wel weg, maar vertrouwde op de eerstvolgende
auto-sync. Bovendien is bij deze installatie sprake van de map
`~/slim2/slim`, terwijl een oudere handleiding `~/slim` gebruikte. Daardoor
kan de GUI anders naar een andere cache kijken.

### Als `--refresh` mislukt

De hotfix meldt nu of het gaat om:
- ontbrekende feed voor de GUI-gebruiker;
- ongeldig of ontbrekend instellingenbestand;
- download-/HTTP-fout;
- ongeldig iCalendar-formaat;
- een geldig ICS-abonnement met 0 lessen.

Stuur **alleen** de regels `Synchronisatie:`, `Fout:`, `Lessen ...`,
`Actieve agendaprovider:` en de paden terug. Plaats nooit je privé-URL,
feed-JSON of geheime cloudgegevens in de chat.

Als de agenda na `Synchronisatie: GELUKT` alsnog leeg is, vergelijk dan het
instellingenpad van de GUI en de helper. Controleer eventueel of
cloudinstellingen de agendaprovider later terugzetten op `mock`.

## Testen

In je bestaande Python-venv:

```bash
python3 -m pytest -q tests/test_myx_sync_hotfix.py
python3 -m compileall -q tools/configure_private_myx.py
```

De echte netwerkverbinding en Pi kunnen alleen op de Pi worden getest.
