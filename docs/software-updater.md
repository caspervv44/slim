# WakeSync v8 software-updater

## Kanaal

Standaard accepteert WakeSync uitsluitend de nieuwste **stabiele GitHub
Release** van `caspervv44/slim`. Drafts en prereleases worden niet gebruikt.

De branchfallback is alleen voor development en staat standaard uit:

```bash
export WAKESYNC_UPDATE_ALLOW_BRANCH=1
```

## Controles vóór installatie

- downloadlimiet;
- geldige ZIP;
- geen absolute/`..`-paden;
- geen symlink-members;
- geldige WakeSync-projectstructuur;
- archiefversie = releaseversie;
- optionele SHA-256 als een release checksum-asset bevat.

Een SHA-256-bestand controleert integriteit. Het is op zichzelf geen
cryptografische bouwherkomst-attestation.

## Installatie en rollback

De helper wacht op het sluiten van de oude GUI. Daarna:

1. alle bekende bron-targets naar backup kopiëren;
2. nieuwe targets volledig naar staging kopiëren;
3. vóór iedere eerste mutatie de target in het operatiejournal zetten;
4. target vervangen;
5. `pip install -e .`;
6. `python -m wekker healthcheck`;
7. alleen na succes de update `healthy` markeren en WakeSync herstarten.

Bij iedere fout worden alleen targets uit `journal.started` teruggedraaid.
Een target die vóór de update niet bestond, wordt tijdens rollback verwijderd;
een bestaand target komt uit de backup terug.

Lokale gegevens worden niet vervangen.

## Veilige timing

De GUI start geen updater terwijl het alarm afgaat of gesnoozed is en ook niet
binnen de ingestelde veiligheidsmarge vlak vóór het alarm.

## Release publiceren

Voor v8 hoort zowel `pyproject.toml` als `wekker.__version__` `8.0.0` te
bevatten. Publiceer daarna een GitHub Release met bijvoorbeeld tag `v8.0.0`.

Bij voorkeur bevat de Release een ZIP-asset en een SHA-256-bestand. Zonder
eigen ZIP-asset gebruikt WakeSync de vastgepinde GitHub-release-zipball; er
wordt niet stil naar `main` uitgeweken.

Updaterdiagnose:

```text
wakesync-update.log
.wakesync-update-status.json
.wakesync-update-journal.json   # alleen tijdens een actieve/mislukte transactie
.wakesync-backups/
```
