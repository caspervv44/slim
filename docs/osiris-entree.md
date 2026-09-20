# Osiris / Entree-voorbereiding (ROC Aventus)

## Status

Er is **nog geen echte Osiris- of Entree-koppeling**. Wat er wél is:

- Provider-register (`agenda/providers.py`): `osiris` als
  `OSIRIS – ROC Aventus` (auth: `entree-oidc`, beschikbaar als demo-flow).
- `OsirisAgendaProvider` (`agenda/osiris.py`): vereist een koppeling, geeft
  zonder koppeling een fout met koppel-instructie, mét demo-koppeling
  duidelijk gemarkeerde demodata (`source="osiris-demo"`).
- Auth-abstractie (`agenda/auth.py`): `AuthProvider`-protocol, `AuthStore`
  (alleen link-records, géén wachtwoorden/tokens), `MockEntreeAuth`
  (demo-flow met eenmalige state-tokens).
- Web-flow: provider kiezen → `POST /api/agenda/auth/start` → demo-loginpagina
  → `POST /api/agenda/auth/callback` → gekoppeld. Nergens wachtwoordvelden.

## Beoogde echte flow (later)

1. Gebruiker opent de webinterface → `Agenda koppelen`.
2. Gebruiker kiest `ROC Aventus / Osiris`.
3. Gebruiker klikt `Inloggen met Entree` (echt, geen demo).
4. Browser opent de officiële school/Entree-login (OIDC Authorization Code).
5. Na succes komt de gebruiker terug bij de wekker (redirect-URI).
6. De wekker wisselt de code voor tokens en gebruikt de agenda-API.

## Lokale configuratie (environment, sinds deze versie)

Echte OSIRIS-configuratie loopt uitsluitend via environment-variabelen, zodat
er nooit geheimen in Git, logs of API-responses belanden. Alleen de NAMEN
liggen vast in code (`agenda/osiris.py`) en hier; waarden levert de beheerder:

- `WEKKER_OSIRIS_BASE_URL` — basis-URL van de officiële OSIRIS-API
- `WEKKER_OSIRIS_CLIENT_ID` — Entree/OIDC client-ID van de schoolkoppeling
- `WEKKER_OSIRIS_REDIRECT_URI` — redirect-URI zoals geregistreerd bij Entree

`OsirisConfig.from_env()` valideert de aanwezigheid; de webapp toont onder
Agenda of echte configuratie aanwezig is (`configured`) en zo niet, welke
namen ontbreken (`missing`) — nooit waarden. `.env`-bestanden staan in
`.gitignore`. Zolang configuratie ontbreekt, blijft de demo-flow (expliciet
als demo gelabeld) de enige werkende stand en blijft Mock gewoon werken.

## Nog benodigde informatie (niets aangenomen)

- [ ] Officiële Osiris-API voor ROC Aventus: base-URL, versie, documentatie.
- [ ] Entree (Kennisnet) OIDC-gegevens: issuer/discovery-URL, client-ID,
      redirect-URI-afspraken, vereiste scopes.
- [ ] Welke agenda-eindpunten en velden beschikbaar zijn (les, docent, lokaal).
- [ ] Token-beleid: geldigheidsduur, refresh-mogelijkheid.
- [ ] Veilige tokenopslag op de Pi (OS-keyring of vergelijkbaar; nooit in
      `wekker-settings.json` of logs).
- [ ] Schoolcontact: wie geeft de koppeling vrij en wat zijn de
      gebruiksvoorwaarden?

Tot die gegevens er zijn, blijft de demo-flow actief en als zodanig gelabeld.

## Toekomstige providers (Somtoday, Magister, …)

Zelfde patroon per platform, zonder school-ifs in de core:

1. `ProviderInfo` op `available=True` zetten in het register.
2. `XxxAgendaProvider(AgendaProvider)` implementeren (alleen fetch + mapping
   naar `Lesson`).
3. Indien nodig een `AuthProvider`-implementatie toevoegen en registreren in
   `AuthService.providers`.
4. Tak toevoegen in `create_provider()` + tests (register, mapping,
   foutpaden, simulated-markering).

## Security-regels (blijvend)

- Nooit schoolwachtwoorden accepteren of opslaan (ook niet "tijdelijk").
- Tokens alleen in veilige opslag; nooit in settings-bestanden of logs
  (log-redactie is al actief).
- State-tokens: eenmalig, kort geldig, strikt gevalideerd.
- Webinterface alleen op het lokale netwerk; geen externe toegang zonder
  authenticatie/TLS (zie README).
