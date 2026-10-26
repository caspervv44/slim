# WakeSync 10.2.1 — definitieve samenvoeging voor jouw broncode

> **Gericht gerepareerd op basis van de twee bestanden uit `WakeSync-broncode-voor-fix.zip`.**
> De eerdere veiligheidsstop bij `premium.py` ontstond doordat jouw 10.2.0-code
> een `try/except TypeError`-fallback had die in de oorspronkelijke basis ontbrak.
> De nieuwe `premium.py` **behoudt die fallback** én voegt de 10.2.1-functies toe.
> De installer herkent de exacte SHA-256 van jouw aangeleverde broncode (zowel LF als CRLF).
> Bij andere/conflicterende wijzigingen blijft de veiligheidsstop bestaan.
>
> **Geen reset nodig en niets opnieuw clonen.** Pak deze ZIP uit over de twee
> eerdere 10.2.1-updatepakketten in je bestaande `WakeSync-upload`-map.

## Snelle Windows-stappen — precies voor jouw situatie

Open PowerShell op je Windows-pc (niet SSH):

```powershell
cd "$env:USERPROFILE\Downloads\WakeSync-upload"
Expand-Archive -Path "$env:USERPROFILE\Downloads\WakeSync-10.2.1-Gerichte-GitHub-Fix.zip" -DestinationPath . -Force
py -3 tools\apply_wakesync_v1021.py --check
```

**Ga alleen verder als bovenstaand commando meldt:
`Compatibiliteit gecontroleerd. Niets gewijzigd`.**

```powershell
py -3 tools\apply_wakesync_v1021.py --apply
git diff --check
git status --short
```

Controleer eventuele meldingen. Daarna kun je uitsluitend projectcode en
updatebestanden klaarzetten (zonder settings, feeds of caches):

```powershell
git add pyproject.toml src/wekker/__init__.py src/wekker/desktop.py
git add src/wekker/gui/premium.py src/wekker/gui/premium_render.py src/wekker/gui/settings_routes_v1021.py
git add tools/apply_wakesync_v1021.py tools/wakesync_install_common.py tools/install_wakesync_desktop.py tools/wakesync_launch.py
git add tests/test_wakesync_v1021.py tests/test_wakesync_merge_compat.py tests/test_wakesync_v1021_uploaded_source.py
git add updates/v10_2_1 docs/WAKE_SYNC_10_2_1.md docs/TESTRESULTATEN-10.2.1.txt LEESMIJ-WAKESYNC-10.2.1.md
git diff --cached --stat
git commit -m "WakeSync 10.2.1: veilige merge, grotere knoppen en desktopstart"
git push origin main
```

Voer de `git add`- en pushstappen **niet uit** wanneer de check of installatie
stopt met `Veiligheidsstop`. Je hoeft dan niets te forceren; stuur de foutmelding.

## Betekenis van deze fix

- Behoudt de testcompatibiliteit van `PremiumTouchApp.__init__`: proberen met drie
  argumenten, bij `TypeError` terugvallen op twee argumenten.
- Behoudt de premium schermen, thema-ID's, alarmen, agenda en sleepscreens.
- Voegt de 10.2.1-grotere knoppen, lagere tabnavigatie en de correcte instellingenroutes toe.
- Voegt de desktopstarter, bureaubladkoppeling en labwc-autostart-installatie toe.
- Past **niet** je bestaande touchmatrix aan: `~/.config/labwc/rc.xml` blijft intact.

## Validatie van de reparatie

Voor deze exact aangeleverde `premium.py` is een regressietest toegevoegd:
`tests/test_wakesync_v1021_uploaded_source.py`. Die test dat de upload herkend wordt,
de 2/3-argumentenfallback behouden blijft, de installatie idempotent is en een
transactie volledig kan worden teruggedraaid. De oorspronkelijke vijf
samenvoegtests blijven aanwezig.

**Let op:** de twee geüploade GUI-bestanden bevatten niet je hele GitHub-kloon,
dus de installer controleert op jouw Windows-pc nog de echte `app.py`, routes
en overige bronbestanden vóór een wijziging. De fysieke Pi en het werkelijk
openen van Software/Diagnose moeten daarna getest worden.

---

# WakeSync 10.2.1 — starten & grotere bediening

> **Compatibiliteitsupdate voor GitHub-clones (26 oktober 2026).**
> Heb je de oude ZIP al uitgepakt en krijg je een `Veiligheidsstop` voor
> `src/wekker/gui/premium.py`? Pak deze nieuwe ZIP in **dezelfde repository**
> uit. De aangepaste installer probeert een gecontroleerde drie-weg-samenvoeging.
> Hij bewaart niet-overlappende eigen wijzigingen en stopt vóór er iets wordt
> geschreven wanneer beide versies hetzelfde stuk code hebben aangepast.
> De code van GitHub is niet rechtstreeks opgehaald, dus `--check` moet op
> jouw lokale clone aantonen of de samenvoeging werkelijk lukt.


Gericht updatepakket voor het eerder geleverde **WakeSync Premium 10.2.0**.
Dit is geen volledige repository en geen al gepubliceerde GitHub-release.

## Wat deze update doet

- Bureaubladsnelkoppeling `WakeSync` en een vermelding in het toepassingsmenu.
  Dubbelklikken start de wekker. De extra snelkoppelingsactie `Projectmap openen`
  opent de bronmap in de bestandsbeheerder.
- Automatisch starten wanneer de persoonlijke **labwc-desktopsessie** begint.
- `wakesync` als terminalcommando, zonder steeds `cd` of venv-activatie.
- De starter kiest de eigen `.venv`, projectmap en het absolute pad naar het
  bestaande `wekker-settings.json`. Vanuit SSH wordt de bestaande lokale
  grafische sessie van dezelfde gebruiker gezocht; er wordt geen `xhost` gebruikt.
- Geen tweede GUI bij dubbel starten via de nieuwe starter. Bij een tweede
  handmatige start wordt het bestaande venster gevraagd naar voren te komen.
  De compositor kan focusverzoeken beperken. Een al buiten deze starter gestart
  `python -m wekker gui` wordt niet beëindigd; sluit dat oude venster eerst.
- Grotere compacte knoppen, vier ongewijzigde thema's, dezelfde kaartindeling.
- De tabknoppen staan visueel ongeveer 6 pixels lager.
- De Software- en Diagnose-tegels zijn weer aan schermacties gekoppeld.

## Wat nadrukkelijk NIET wordt gewijzigd

De update leest of schrijft geen touchkalibratie. `~/.config/labwc/rc.xml`,
udev-regels en `/boot/firmware/config.txt` blijven intact. De reeds bewaarde
werkende kalibratie blijft dus buiten de applicatie.

Privéfeed, instellingen, alarmen, cache, MyX-parser, de bestaande agendahotfixes,
logo's, landschapsassets, audiodriver en `test2.pl` worden niet vervangen.
De software-updater wordt niet herschreven: de tegel opent bestaande functies.

De desktopinstaller voegt uitsluitend persoonlijke startbestanden toe:
de snelkoppeling, menukoppeling, `~/.local/bin/wakesync`, een beheerd PATH-blok
in de shellprofielen en een herkenbaar blok in `~/.config/labwc/autostart`.
Hij controleert voor/na dat `rc.xml` bytegelijk is gebleven.

## Basis en veiligheidscontrole

De actuele GitHub-inhoud kon tijdens deze levering niet worden opgehaald.
De wijziging is gebouwd tegen de concrete 10.2.0-bestanden uit het eerdere ZIP-pakket.

**Daarom nooit ongecontroleerd src-bestanden overschrijven.** De gewijzigde
bestanden staan eerst onder `updates/v10_2_1/payload`. De installer:
1. controleert de bronversie en hashes (CRLF/LF is toegestaan);
2. leest met AST de werkelijke `TouchApp` in jouw clone;
3. zoekt aantoonbaar bestaande Software-/Diagnose-functies;
4. voegt niet-overlappende premium-wijzigingen samen en controleert Python-syntax;
5. maakt pas daarna een back-up buiten de repository;
6. schrijft gecontroleerd de nieuwe code en versie 10.2.1.

Voor de twee premium-bronbestanden bevat het updatepakket nu een gecontroleerde
**Git-drie-weg-samenvoeging**: eerdere versie (basis), jouw huidige GitHub-versie
en de nieuwe 10.2.1-versie. Alleen niet-overlappende aanpassingen worden
samengevoegd. Dat is geen garantie dat alle logisch gewijzigde functies
automatisch compatibel zijn: controleer altijd `git diff` vóór een push.

Bij een conflict of ontbrekende schermfunctie stopt de installer zonder de
bronbestanden te veranderen. **Gebruik nooit `git reset --hard`, `git checkout`
of een geforceerde bronvervanging als oplossing voor die melding.**
Upload bij een conflict het genoemde `.py`-bestand; dan kan de samenvoeging
gericht worden aangepast.

## A. Lokaal voorbereiden en naar GitHub pushen

Vereist voor de source-installer: Python 3.11 of hoger. Je Pi gebruikt Python 3.13.

Pak de inhoud van de ZIP uit in de **hoofdmap van je bestaande slim-repository**.
`tools`, `tests`, `docs` en `updates` moeten naast `pyproject.toml` staan.
Pak dus niet uit over je home-directory of in een nieuwe lege projectmap.

Controleer eerst de werkboom en de update:

```bash
git status --short
python tools/apply_wakesync_v1021.py --check
```

Op Windows kan `py -3` in plaats van `python` nodig zijn. Op Linux is `python3`
ook geschikt. De source-installer heeft geen extra Python-pakketten nodig.

Pas daarna toe:

```bash
python tools/apply_wakesync_v1021.py --apply
git diff --check
git diff --stat
git diff -- src/wekker/gui/premium.py src/wekker/gui/premium_render.py
```

Commit/push de nieuwe en gewijzigde projectbestanden. Voeg niet blind privédata toe.
Een gerichte selectie is:

```bash
git add pyproject.toml src/wekker/__init__.py src/wekker/desktop.py
git add src/wekker/gui/premium.py src/wekker/gui/premium_render.py src/wekker/gui/settings_routes_v1021.py
git add tools/apply_wakesync_v1021.py tools/wakesync_install_common.py tools/install_wakesync_desktop.py tools/wakesync_launch.py
git add tests/test_wakesync_v1021.py tests/test_wakesync_merge_compat.py updates/v10_2_1 docs/WAKE_SYNC_10_2_1.md docs/TESTRESULTATEN-10.2.1.txt LEESMIJ-WAKESYNC-10.2.1.md
git commit -m "WakeSync 10.2.1: desktopstart, grotere knoppen en instellingenroutes"
git push
```

Laat je privé `wekker-settings.json`, feedbestanden, caches en meetrapporten buiten
de commit. Dit pakket bevat die bestanden niet.

Je kunt de source-update ook op de Pi toepassen, maar commit/push dan eerst die
bronwijzigingen voordat je weer een `git pull` doet. Zo voorkom je lokale conflicten.

## B. Installeren op de Raspberry Pi

Sluit eerst de lopende WakeSync-GUI normaal af. De nieuwe code wordt niet door een
al geopend Python-proces ingeladen.

Voer als `casper`, zonder sudo, via SSH of een lokale terminal uit:

```bash
cd ~/slim2/slim
git pull --ff-only
source .venv/bin/activate
python3 -m pip install -e .
python3 -m pytest -q tests/test_wakesync_v1021.py
python3 tools/install_wakesync_desktop.py --install --autostart
export PATH="$HOME/.local/bin:$PATH"
hash -r
wakesync --check
wakesync
```

Voer na `--check` bij een fout niet verder uit; de melding geeft aan wat ontbreekt.
De source-installer is niet nogmaals nodig wanneer de toegepaste wijzigingen
al gecommit en gepulld zijn. Nogmaals uitvoeren is wel idempotent.

De desktopinstaller hoort alleen op de echte Pi te draaien, niet op Windows.
Hij gebruikt het pad van de clone waar hij zich bevindt, dus niet ongemerkt
`~/slim` wanneer jij `~/slim2/slim` gebruikt.

Bij de eerste dubbelklik kan je bureaublad vragen om `Uitvoeren toestaan`.
Het bestand krijgt uitvoerrechten; de installer probeert daarnaast de ondersteunde
GIO-vertrouwensmarkering te zetten.

### Opstarten is opstarten van de desktop

De autostart start de app na aanmelding op het labwc-bureaublad. Als je Pi al
automatisch grafisch inlogt, opent WakeSync dus na het aanzetten. Zonder
desktop-autologin moet je eerst grafisch aanmelden. Deze update verandert geen
wachtwoorden, loginbeleid of automatische-aanmeldinstellingen.

Bij SSH zonder lokaal aangemeld bureaublad is er geen schermsessie om op te openen;
de starter meldt dat dan in plaats van te gokken op `DISPLAY=:0`.

## C. Controle op het echte apparaat

Controleer eerst de nieuwe versie met:

```bash
wakesync --version
```

Verwacht: `WakeSync 10.2.1`.

Controleer de vier tabs, dagpijlen en alarmknoppen met de pen. De software voegt
geen tweede kalibratiematrix toe. Open ook Instellingen → Software en Diagnose,
en sluit beide schermen weer normaal.

Start WakeSync nogmaals via de snelkoppeling terwijl het al openstaat. Er mag
geen tweede wekker starten via de nieuwe starter. Sluit de app en test vervolgens
het commando `wakesync`.

Herstart de Pi om het autostartgedrag en de al bestaande touchkalibratie te testen.
Dit is een echte hardwarecontrole; de lokale ontwikkeltests vervangen dit niet.
Controleer je alarm en speaker voordat je op de bijgewerkte wekker vertrouwt.

## D. Log en terugzetten

De nieuwe starter bewaart zijn GUI-log lokaal, afgeschermd:

```text
~/.local/state/wakesync/gui.log
```

Een log kan runtime-informatie bevatten. Deel geen privéfeed of volledige
gevoelige configuratie uit een log.

Autostart uitschakelen, zonder de snelkoppeling te verwijderen:

```bash
python3 tools/install_wakesync_desktop.py --disable-autostart
```

De source-installer en desktopinstaller melden ieder hun eigen herstelmanifest.
Bewaar dat pad. Herstellen kan met het betreffende programma:

```bash
python3 tools/apply_wakesync_v1021.py --restore "/volledig/pad/naar/manifest.json"
python3 -m pip install -e .
```

of voor alleen persoonlijke startbestanden:

```bash
python3 tools/install_wakesync_desktop.py --restore "/volledig/pad/naar/manifest.json"
```

Herstel weigert bestanden die na de installatie verder zijn gewijzigd; zo worden
latere gebruikerswijzigingen niet stilzwijgend weggegooid. Bij een stroomuitval
tijdens installatie zijn back-ups beschikbaar, maar herstel kan handmatige
controle vereisen.

## Testgrenzen

105 lokale regressietests geslaagd tegen de geleverde renderer, starter,
installerlogica en een expliciete legacy-interfacefixture.
Daarnaast zijn acht Software/Diagnose-klikken met echte Tk-events op een
virtueel 800×480-display gecontroleerd. De canvas blijft bij tabwissels bestaan.

Niet getest: jouw volledige actuele repository, daadwerkelijke bestaande
legacy-overlayinhoud, echt Pi-opstarten, labwc-focusgedrag en fysieke alarmhardware.
De installer controleert de relevante echte functies lokaal vóór schrijven.

Zie `docs/TESTRESULTATEN-10.2.1.txt` voor de uitgevoerde controles.
