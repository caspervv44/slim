"""Lokale setup-API op basis van de standaardbibliotheek.

Bewuste keuze: geen Flask/FastAPI, zodat de Pi geen extra dependencies nodig
heeft en de wekker ook zonder telefoon zelfstandig blijft werken. De API is
alleen een dunne schil over core/settings/agenda/button-controller; alle
logica leeft elders.

Eerste prototype (geen motor-, wiel- of touch-endpoints):

  POST /api/login           prototype-login (casper/casper) → sessiecookie
  POST /api/logout          sessie intrekken
  GET  /api/status          toestand, tijd, tijdzone, volgend alarm, lamp, speaker
  GET  /api/settings        huidige instellingen
  POST /api/settings        gedeeltelijke update, bv. {"alarm": {"time": "07:00"}}
  GET  /api/agenda/status   syncstatus + beschikbare providers
  GET  /api/agenda/providers  alle schoolplatformen + koppelstatus
  GET  /api/agenda/items    lessen van vandaag (alleen mock; anders 501)
  GET  /api/agenda/auth/status   koppelstatus huidige provider
  POST /api/agenda/auth/start    start (demo-)Entree-login → {auth_url, state}
  GET  /api/agenda/auth/mock?state=..  demo-loginpagina (géén echte Entree)
  POST /api/agenda/auth/callback {state}  rond login af → gekoppeld
  POST /api/agenda/auth/disconnect  verbreek koppeling
  POST /api/lamp/on         {"duration_seconds": 30} (optioneel)
  POST /api/lamp/off        lamp uit
  POST /api/lamp/test       lamp 3 s aan (test)
  POST /api/speaker/test    kort testgeluid (±1 s)
  POST /api/alarm/dismiss   alarm afhandelen (lokaal prototype)
  POST /api/button/press    simuleer de fysieke button
  GET  /                    mobiele setup-interface
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from wekker.agenda.auth import AuthError, AuthService, MAX_STATE_LEN
from wekker.agenda.cache import AgendaCache
from wekker.agenda.models import SIMULATED_SOURCES
from wekker.agenda.osiris import OsirisConfig
from wekker.agenda.myx import MyXConfig
from wekker.agenda.myx_auth import MyXAuthError, MyXAuthManager
from wekker.agenda.providers import (
    build_sync_provider,
    get_provider_info,
    list_providers,
)
from wekker.api.webauth import (
    SESSION_COOKIE,
    SESSION_TTL,
    SessionStore,
    WebAuthError,
    parse_cookies,
)
from wekker.agenda.sync import AgendaSyncService
from wekker.alarm.core import AlarmClock
from wekker.button.controller import ButtonController
from wekker.clock import Clock, SystemClock
from wekker.display.manager import DisplayManager
from wekker.settings import ALLOWED_PROVIDERS, Settings, SettingsError
from wekker.storage import JsonStore, StorageError

log = logging.getLogger(__name__)

# Prototypegrens: stel nooit meer dan 64 KiB in één request bij. De setup-API
# accepteert alleen kleine JSON-patches; ongelimiteerd lezen maakt de Pi
# kwetsbaar voor geheugenuitputting door één verkeerd request.
MAX_BODY_BYTES = 64 * 1024

#: Duur van de lamp-test via de setup-app.
LAMP_TEST_SECONDS = 3

#: Duur van het speaker-testgeluid.
SPEAKER_TEST_SECONDS = 1


class BodyTooLargeError(Exception):
    """Request-body groter dan MAX_BODY_BYTES."""


@dataclass
class AppContext:
    settings: Settings
    store: JsonStore
    clock: Clock
    core: AlarmClock
    display: DisplayManager
    cache: AgendaCache
    sync: AgendaSyncService
    button: ButtonController
    auth: AuthService
    # Prototype-weblogin (casper/casper). Default is een eigen store zodat
    # bestaande constructie (ook in tests) blijft werken; de productiecode
    # gebruikt dezelfde SystemClock als de rest van de Runtime.
    sessions: SessionStore = field(default_factory=lambda: SessionStore(SystemClock()))
    myx_auth: MyXAuthManager | None = None


INDEX_HTML = """<!doctype html><html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Wekker setup</title>
<style>
:root{color-scheme:light}
body{font-family:system-ui,sans-serif;margin:0;padding:0 1rem 3rem;max-width:560px;margin-inline:auto}
h1{font-size:1.4rem}h2{font-size:1.1rem;margin-top:1.5rem;border-top:1px solid #ddd;padding-top:1rem}
.card{background:#f6f6f6;border-radius:.6rem;padding:.8rem;margin:.5rem 0}
.row{display:flex;gap:.5rem;flex-wrap:wrap;margin:.4rem 0}
button,input,select{font-size:1rem;padding:.55rem .7rem;border-radius:.5rem;border:1px solid #bbb}
button{background:#fff}button:active{background:#e6e6e6}
button.primary{background:#0a6cff;color:#fff;border-color:#0a6cff}
pre{background:#eee;padding:.7rem;overflow:auto;border-radius:.5rem;font-size:.85rem}
.badge{display:inline-block;background:#ffd75e;border-radius:.4rem;padding:.1rem .5rem;font-size:.8rem}
table{border-collapse:collapse;width:100%;font-size:.9rem}
td,th{border-bottom:1px solid #ddd;padding:.3rem;text-align:left}
#err{color:#b00020}
</style>
</head><body>
<h1>Aventus Wekker</h1>
<p>De wekker werkt zelfstandig; deze pagina is alleen voor instellen. Prototype met login.</p>
<div class="row"><button class="primary" onclick="ping()">Verbinding testen</button><span id="ping"></span>
<button onclick="uitloggen()">Uitloggen</button></div>

<h2>Status</h2>
<div class="card">
Toestand: <b id="st_state">laden…</b><br>Tijd: <span id="st_time">–</span> (<span id="st_tz">–</span>)
<br>Volgende alarm: <span id="st_alarm">–</span>
<br>Lamp: <span id="st_lamp">–</span> · Speaker: <span id="st_speaker">–</span>
<br>Agenda: <span id="st_agenda">–</span>
<br>Verbinding: <span id="st_conn">–</span>
</div>
<p id="err"></p>

<h2>Lamp</h2>
<div class="row">
<button onclick="act('/api/lamp/on',{duration_seconds:30})">Lamp 30 s aan</button>
<button onclick="act('/api/lamp/off')">Lamp uit</button>
<button onclick="act('/api/lamp/test')">Lamp testen</button>
</div>

<h2>Speaker</h2>
<div class="row"><button onclick="act('/api/speaker/test')">Testgeluid</button></div>

<h2>Alarm &amp; button</h2>
<div class="row">
<button onclick="act('/api/alarm/dismiss')">Alarm afhandelen</button>
<button onclick="act('/api/button/press')">Button indrukken (simulatie)</button>
</div>

<h2>Instellingen</h2>
<div class="row">
<label>Wektijd <input id="f_time" value="07:30" size="5"></label>
<label>Lampduur na button (s) <input id="f_lampdur" value="30" size="4" inputmode="numeric"></label>
</div>
<div class="row">
<label><input type="checkbox" id="f_spk" checked> Speaker bij alarm</label>
<label><input type="checkbox" id="f_lamp" checked> Lamp bij alarm</label>
</div>
<div class="row">
<label>Geluid <input id="f_sound" value="beep" size="8"></label>
<label>Agenda <select id="f_prov"></select></label>
</div>
<div class="row"><button class="primary" onclick="save()">Opslaan</button></div>
<pre id="settings">laden…</pre>

<h2>Agenda</h2>
<div class="card" id="auth">laden…</div>
<div class="row"><button onclick="act('/api/agenda/auth/disconnect')">Koppeling verbreken</button></div>
<div class="card" id="sync">laden…</div>
<div id="agenda">laden…</div>

<script>
// Live updates zonder page reload: één pagina blijft bestaan; per tick worden
// alleen veranderde teksten aangepast (setText) en zelden wijzigende kaarten
// (auth/sync/agenda) alleen bij gewijzigde inhoud opnieuw opgebouwd. Het
// instellingenformulier wordt ALLEEN bij opstarten en na Opslaan gevuld,
// zodat typen nooit door polling wordt overschreven.
const $=id=>document.getElementById(id);
function setText(id,v){const e=$(id);if(e&&e.textContent!==v)e.textContent=v;}
async function jget(u){const r=await fetch(u);if(r.status===401){location='/login';throw new Error('login vereist')}const b=await r.json();if(!r.ok)throw new Error(b.error||r.status);return b}
async function jpost(u,b){const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})});if(r.status===401){location='/login';throw new Error('login vereist')}const d=await r.json();if(!r.ok)throw new Error(d.error||r.status);return d}
async function uitloggen(){try{await jpost('/api/logout',{})}catch(e){}location='/login'}
async function ping(){try{await jget('/api/status');setText('ping','✓ verbonden')}catch(e){setText('ping','✗ '+e)}}
function renderAuth(a){
 let h='Agenda: <b>'+a.provider_name+'</b> ('+a.school+')<br>';
 if(a.provider==='myx'){
   if(a.busy){h+='MyX-login is bezig op het scherm van de wekker…'}
   else if(a.linked&&a.token_valid){h+='✓ Gekoppeld als '+(a.account||'Aventus-student')}
   else if(a.linked){h+='MyX gekoppeld, maar opnieuw inloggen is nodig.'}
   else{h+='Niet gekoppeld. <button class="primary" onclick="link()">Inloggen met Aventus / MyX</button>'}
   if(a.expires_at&&a.token_valid){h+='<br>Token geldig tot '+a.expires_at.slice(0,16).replace('T',' ')}
   if(a.auth_error){h+='<br>'+a.auth_error}
 } else if(a.linked){h+='Gekoppeld als '+a.account+(a.demo?' (demo)':'')}
 else if(a.available&&a.login_label){h+='Niet gekoppeld. <button class="primary" onclick="link()">'+a.login_label+'</button>'}
 else{h+='Nog niet beschikbaar voor dit platform.'}
 if(a.provider==='osiris'&&!a.configured){h+='<br><span class="badge">demo</span> Geen echte OSIRIS-configuratie — zie docs/osiris-entree.md.'}
 if($('auth').innerHTML!==h)$('auth').innerHTML=h;
}
function renderSync(g){
 const h='Sync: '+g.status+(g.last_sync?' ('+g.last_sync.slice(0,16).replace('T',' ')+')':'')
  +(g.stale?' · <b>mogelijk verouderd</b>':' · actueel')
  +(g.error?'<br>Fout: '+g.error:'');
 if($('sync').innerHTML!==h)$('sync').innerHTML=h;
}
function renderAgenda(a){
 const h=(a.simulated?'<span class="badge">gesimuleerd (mock)</span> ':'')
  +'<table>'+a.items.map(i=>'<tr><td>'+i.start_time.slice(11,16)+'</td><td>'+i.subject+'</td><td>'+i.location+'</td></tr>').join('')+'</table>';
 if($('agenda').innerHTML!==h)$('agenda').innerHTML=h;
}
let lastAuth='',lastSync='',lastAgenda='';
async function tick(){
 try{
  const s=await jget('/api/status');
  setText('st_state',s.state);
  setText('st_time',s.now.slice(11,19));
  setText('st_tz',s.timezone);
  setText('st_alarm',s.next_alarm?s.next_alarm.slice(0,16).replace('T',' '):'uit');
  setText('st_lamp',s.lamp_on?'aan':'uit');
  setText('st_speaker',s.speaker_playing?'aan':'uit');
  const astat=await jget('/api/agenda/auth/status');
  setText('st_agenda',astat.provider_name+(astat.linked?' (gekoppeld)':''));
  setText('st_conn','verbonden');
  const sigA=JSON.stringify([astat.provider,astat.linked,astat.account,astat.demo,astat.available,astat.configured]);
  if(sigA!==lastAuth){lastAuth=sigA;renderAuth(astat);}
  const gstat=await jget('/api/agenda/status');
  const sigS=JSON.stringify(gstat);
  if(sigS!==lastSync){lastSync=sigS;renderSync(gstat);}
  try{
   const a=await jget('/api/agenda/items');
   const sigG=JSON.stringify(a);
   if(sigG!==lastAgenda){lastAgenda=sigG;renderAgenda(a);}
  }catch(e){
   const m='Agenda: '+e.message;
   if(m!==lastAgenda){lastAgenda=m;setText('agenda',m);}
  }
  setText('err','');
 }catch(e){setText('err','Fout: '+e.message);}
}
async function fillForm(){
 const c=await jget('/api/settings');
 $('settings').textContent=JSON.stringify(c,null,1);
 // Alleen hier (opstarten/na Opslaan) worden formuliervelden gevuld.
 $('f_time').value=c.alarm.time;$('f_lampdur').value=c.lamp.duration_after_button;
 $('f_spk').checked=c.alarm.speaker_enabled;$('f_lamp').checked=c.lamp.on_with_alarm;
 $('f_sound').value=c.alarm.sound;
 const prov=$('f_prov');prov.innerHTML='';
 const plist=await jget('/api/agenda/providers');
 plist.providers.forEach(p=>{const o=document.createElement('option');o.value=p.id;
  o.textContent=p.display_name+(p.available?'':' (later)');if(p.selected)o.selected=true;prov.appendChild(o)});
}
async function act(u,b){try{await jpost(u,b)}catch(e){setText('err','Fout: '+e.message)}tick();}
async function link(){
 try{
  // Sla eerst de gekozen provider op, start dan de login-flow.
  await jpost('/api/settings',{agenda:{provider:$('f_prov').value}});
  const f=await jpost('/api/agenda/auth/start',{});
  if(f.auth_url){
    window.open(f.auth_url,'_blank');
    alert('Rond de login af in het geopende venster en druk daarna op OK.');
  }else{
    setText('err',f.message||'Login geopend op het scherm van de wekker.');
  }
 }catch(e){setText('err','Fout: '+e.message)}
 tick();
}
async function save(){
 const body={alarm:{time:$('f_time').value,speaker_enabled:$('f_spk').checked,sound:$('f_sound').value},
  lamp:{duration_after_button:parseInt($('f_lampdur').value,10),on_with_alarm:$('f_lamp').checked},
  agenda:{provider:$('f_prov').value}};
 try{await jpost('/api/settings',body);await fillForm()}catch(e){setText('err','Fout: '+e.message)}tick();
}
fillForm();tick();setInterval(tick,3000);
</script></body></html>"""

LOGIN_HTML = """<!doctype html><html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Wekker login</title>
<style>
body{font-family:system-ui,sans-serif;max-width:420px;margin:3rem auto;padding:0 1rem}
.card{background:#f6f6f6;border-radius:.6rem;padding:1rem}
.row{display:flex;gap:.5rem;margin:.5rem 0}
button,input{font-size:1rem;padding:.55rem .7rem;border-radius:.5rem;border:1px solid #bbb}
button.primary{background:#0a6cff;color:#fff;border-color:#0a6cff}
#msg{color:#b00020}
</style>
</head><body>
<h1>Aventus Wekker</h1>
<div class="card">
<h2>Inloggen (prototype)</h2>
<div class="row"><label>Gebruiker <input id="f_user" autocomplete="username"></label></div>
<div class="row"><label>Wachtwoord <input id="f_pass" type="password" autocomplete="current-password"></label></div>
<div class="row"><button class="primary" onclick="login()">Inloggen</button></div>
<p id="msg"></p>
</div>
<script>
async function login(){
 const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({username:document.getElementById('f_user').value,
   password:document.getElementById('f_pass').value})});
 if(r.ok){location='/'}else{
  let m='Inloggen mislukt';
  try{m=(await r.json()).error||m}catch(e){}
  document.getElementById('msg').textContent=m;
 }
}
</script></body></html>"""


def _send(handler: BaseHTTPRequestHandler, code: int, payload: object,
          extra_headers: list[tuple[str, str]] | None = None) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    for naam, waarde in extra_headers or []:
        handler.send_header(naam, waarde)
    handler.end_headers()
    handler.wfile.write(body)


def _session_cookie_header(token: str) -> str:
    max_age = int(SESSION_TTL.total_seconds())
    return (f"{SESSION_COOKIE}={token}; Path=/; Max-Age={max_age}; "
            "HttpOnly; SameSite=Lax")


def _cleared_cookie_header() -> str:
    return f"{SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"


def _apply_settings(ctx: AppContext, patch: dict) -> dict:
    """Valideer, activeer en bewaar nieuwe instellingen. Geeft dict terug."""
    nieuwe = ctx.settings.update_from_dict(patch)
    ctx.settings = nieuwe
    ctx.core.update_settings(nieuwe)
    ctx.display.update_settings(nieuwe)
    ctx.button.update_settings(nieuwe)
    # Providerwissel: bouw de passende adapter (mock direct, osiris met
    # koppeling, overige eerlijk "nog niet beschikbaar").
    ctx.sync = build_sync_provider(nieuwe.agenda.provider, ctx.cache, ctx.clock, ctx.auth, ctx.myx_auth)
    try:
        ctx.store.save(nieuwe.to_dict())
    except StorageError as exc:
        log.warning("opslaan mislukt (instellingen wel actief): %s", exc)
        return {**nieuwe.to_dict(), "warning": str(exc)}
    return nieuwe.to_dict()


def _is_connected(ctx: AppContext) -> bool:
    """Heeft de gekozen provider bruikbare data? mock altijd; osiris alleen
    gekoppeld; overige platforms nooit (nog niet beschikbaar)."""
    provider_id = ctx.settings.agenda.provider
    if provider_id == "mock":
        return True
    if provider_id == "osiris":
        return ctx.auth.is_linked("osiris")
    if provider_id == "myx":
        if ctx.myx_auth is not None:
            return bool(ctx.myx_auth.status()["linked"])
        return MyXConfig.from_env().configured
    return False


def _send_html(handler: BaseHTTPRequestHandler, html: str) -> None:
    body = html.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _valid_state(state: str) -> bool:
    """Strenge validatie van login-state-tokens (alleen URL-veilige tekens)."""
    if not isinstance(state, str) or not state or len(state) > MAX_STATE_LEN:
        return False
    return all(c.isalnum() or c in "-_" for c in state)


def _mock_login_page(state: str) -> str:
    """Demo-loginpagina. Expliciet géén echte Entree-login: er wordt nergens
    om een gebruikersnaam of wachtwoord gevraagd."""
    return f"""<!doctype html><html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Demo-login (geen echte Entree)</title>
<style>body{{font-family:system-ui,sans-serif;max-width:560px;margin:2rem auto;padding:0 1rem}}
.badge{{background:#ffd75e;border-radius:.4rem;padding:.2rem .6rem}}</style>
</head><body>
<h1>Demo-login <span class="badge">DEMO</span></h1>
<p>Dit is een <b>gesimuleerde</b> Entree-login voor development. Er wordt
<b>nergens om een wachtwoord gevraagd</b> en er worden geen echte
schooldaten opgehaald.</p>
<div class="row"><button style="font-size:1.1rem;padding:.7rem 1rem"
onclick="doorgaan()">Doorgaan als demo-student</button></div>
<p id="msg"></p>
<script>
async function doorgaan(){{
 const r=await fetch('/api/agenda/auth/callback',{{method:'POST',
  headers:{{'Content-Type':'application/json'}},
  body:JSON.stringify({{state:{state!r}}})}});
 const b=await r.json();
 if(r.ok){{document.getElementById('msg').textContent='Gekoppeld als '+b.account+'. Je kunt terug naar de wekker.'}}
 else{{document.getElementById('msg').textContent='Fout: '+(b.error||r.status)}}
}}
</script></body></html>"""


def _send_items(handler: BaseHTTPRequestHandler, ctx: AppContext) -> None:
    provider_id = ctx.settings.agenda.provider
    if provider_id == "osiris" and not ctx.auth.is_linked("osiris"):
        _send(handler, 409, {
            "error": "Osiris is niet gekoppeld. Koppel via 'Agenda koppelen' "
                     "→ 'ROC Aventus / Osiris'.",
            "action": "link",
        })
        return
    if provider_id == "myx":
        cfg = MyXConfig.from_env()
        if not cfg.configured:
            _send(handler, 409, {
                "error": "MyX is niet geconfigureerd. Ontbrekend: "
                         + ", ".join(cfg.missing()),
                "action": "configure-environment",
            })
            return
    elif provider_id not in ("mock", "osiris"):
        _send(handler, 501, {
            "error": f"Provider {provider_id!r} nog niet "
                     "beschikbaar; kies 'mock' voor voorbeeldgegevens.",
        })
        return
    lessen = ctx.cache.get_day(ctx.clock.now().date())
    _send(handler, 200, {
        "simulated": all(les.source in SIMULATED_SOURCES for les in lessen),
        "provider": provider_id,
        "items": [les.to_dict() for les in lessen],
    })


def make_handler(ctx: AppContext) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "WekkerSetup/0.2"

        def log_message(self, fmt: str, *args: object) -> None:
            log.info("%s %s", self.address_string(), fmt % args)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                raise BodyTooLargeError(f"Body van {length} bytes > limiet {MAX_BODY_BYTES}")
            if length <= 0:
                return {}
            try:
                raw = self.rfile.read(length).decode("utf-8")
                data = json.loads(raw) if raw.strip() else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise SettingsError("Ongeldige JSON-body")
            if not isinstance(data, dict):
                raise SettingsError("Body moet een JSON-object zijn")
            return data

        def _status_dict(self) -> dict:
            data = ctx.core.status()
            data["display_visible"] = ctx.display.visible
            data["lamp_on"] = ctx.button.lamp_is_on
            data["lamp_timer_active"] = ctx.button.lamp_timer_active
            data["speaker_playing"] = ctx.core.speaker_playing
            data["agenda_stale"] = ctx.cache.is_stale(ctx.clock.now())
            data["timezone"] = ctx.settings.locale.timezone
            data["region"] = ctx.settings.locale.region
            return data

        def _session_token(self) -> str | None:
            return parse_cookies(self.headers.get("Cookie")).get(SESSION_COOKIE)

        def _logged_in(self) -> bool:
            return ctx.sessions.valid(self._session_token())

        def _base_url(self) -> str:
            host, port = self.server.server_address[:2]
            return f"http://{host}:{port}"

        def _query(self) -> dict:
            return parse_qs(urlparse(self.path).query)

        def _auth_status_dict(self) -> dict:
            provider_id = ctx.settings.agenda.provider
            try:
                info = get_provider_info(provider_id)
            except ValueError:
                return {"provider": provider_id, "error": "Onbekende provider"}
            link = ctx.auth.get_link(provider_id)
            auth_provider = ctx.auth.providers.get(provider_id)
            # Echte OSIRIS-configuratie (alleen namen van ontbrekende vars,
            # nooit waarden). Andere providers kennen dit begrip niet.
            configured, missing = True, []
            if provider_id == "osiris":
                cfg = OsirisConfig.from_env()
                configured, missing = cfg.configured, cfg.missing()
            elif provider_id == "myx":
                if ctx.myx_auth is not None:
                    myx_status = ctx.myx_auth.status()
                    configured = bool(myx_status["linked"])
                    missing = []
                else:
                    cfg = MyXConfig.from_env()
                    configured, missing = cfg.configured, cfg.missing()
            linked = link is not None
            account = link.account_label if link else None
            myx_status = None
            if provider_id == "myx":
                if ctx.myx_auth is not None:
                    myx_status = ctx.myx_auth.status()
                    linked = bool(myx_status["linked"])
                    account = myx_status["account"]
                else:
                    linked = configured
                    account = "lokale MyX-configuratie" if configured else None
            return {
                "provider": provider_id,
                "provider_name": info.display_name,
                "school": info.school,
                "auth": info.auth,
                "available": info.available,
                "linked": linked,
                "account": account,
                "demo": link.demo if link else False,
                "login_label": auth_provider.login_label if auth_provider else None,
                "configured": configured,
                "missing": missing,
                "token_valid": myx_status["token_valid"] if myx_status else None,
                "needs_login": myx_status["needs_login"] if myx_status else None,
                "busy": myx_status["busy"] if myx_status else False,
                "auth_state": myx_status["state"] if myx_status else None,
                "auth_error": myx_status["error"] if myx_status else None,
                "expires_at": myx_status["expires_at"] if myx_status else None,
            }

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            try:
                if path == "/login":
                    _send_html(self, LOGIN_HTML)
                    return
                if not self._logged_in():
                    if path == "/":
                        self.send_response(302)
                        self.send_header("Location", "/login")
                        self.end_headers()
                        return
                    _send(self, 401, {"error": "Inloggen vereist."})
                    return
                if path == "/":
                    body = INDEX_HTML.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif path == "/api/settings":
                    data = ctx.settings.to_dict()
                    data["_providers"] = sorted(ALLOWED_PROVIDERS)
                    _send(self, 200, data)
                elif path == "/api/status":
                    _send(self, 200, self._status_dict())
                elif path == "/api/agenda/status":
                    data = ctx.cache.status_dict()
                    data["provider"] = ctx.sync.provider_name
                    data["available_providers"] = sorted(ALLOWED_PROVIDERS)
                    data["connected"] = _is_connected(ctx)
                    data["linked"] = _is_connected(ctx)
                    data["stale"] = ctx.cache.is_stale(ctx.clock.now())
                    _send(self, 200, data)
                elif path == "/api/agenda/providers":
                    items = []
                    for info in list_providers():
                        items.append({
                            "id": info.id,
                            "display_name": info.display_name,
                            "school": info.school,
                            "auth": info.auth,
                            "available": info.available,
                            "description": info.description,
                            "linked": (
                                bool(ctx.myx_auth.status()["linked"])
                                if info.id == "myx" and ctx.myx_auth is not None
                                else (MyXConfig.from_env().configured
                                      if info.id == "myx"
                                      else ctx.auth.is_linked(info.id))
                            ),
                            "selected": info.id == ctx.settings.agenda.provider,
                        })
                    _send(self, 200, {"providers": items})
                elif path == "/api/agenda/items":
                    _send_items(self, ctx)
                    return
                elif path == "/api/agenda/auth/status":
                    _send(self, 200, self._auth_status_dict())
                    return
                elif path == "/api/agenda/auth/mock":
                    state = self._query().get("state", [""])[0]
                    if not _valid_state(state):
                        _send(self, 400, {"error": "Ongeldige of ontbrekende state."})
                        return
                    _send_html(self, _mock_login_page(state))
                    return
                else:
                    _send(self, 404, {"error": "Onbekend endpoint"})
            except Exception as exc:  # pragma: no cover - defensief
                log.exception("GET %s faalde", path)
                _send(self, 500, {"error": f"Interne fout: {type(exc).__name__}"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                body = self._read_json()
                if path == "/api/login":
                    try:
                        token = ctx.sessions.login(body.get("username"),
                                                   body.get("password"))
                    except WebAuthError as exc:
                        _send(self, 401, {"error": str(exc)})
                        return
                    _send(self, 200, {"ok": True},
                          extra_headers=[("Set-Cookie", _session_cookie_header(token))])
                    return
                if path == "/api/logout":
                    ctx.sessions.logout(self._session_token())
                    _send(self, 200, {"ok": True},
                          extra_headers=[("Set-Cookie", _cleared_cookie_header())])
                    return
                if not self._logged_in():
                    _send(self, 401, {"error": "Inloggen vereist."})
                    return
                if path == "/api/settings":
                    _send(self, 200, _apply_settings(ctx, body))
                elif path == "/api/alarm/dismiss":
                    # Lokaal prototype: afhandelen alsof de button is ingedrukt.
                    # Op het echte product blijft de fysieke button de hoofdweg.
                    ok = ctx.core.dismiss(physical=True)
                    code = 200 if ok else 409
                    _send(self, code, {"ok": ok, "state": ctx.core.state.value})
                elif path == "/api/button/press":
                    resultaat = ctx.button.press()
                    _send(self, 200, {"ok": True, "result": resultaat,
                                      "state": ctx.core.state.value})
                elif path == "/api/lamp/on":
                    duration = body.get("duration_seconds")
                    resultaat = ctx.button.lamp_on(duration)
                    _send(self, 200, {"ok": True, "result": resultaat})
                elif path == "/api/lamp/off":
                    resultaat = ctx.button.lamp_off()
                    _send(self, 200, {"ok": True, "result": resultaat})
                elif path == "/api/lamp/test":
                    resultaat = ctx.button.lamp_on(LAMP_TEST_SECONDS)
                    _send(self, 200, {"ok": True, "result": resultaat})
                elif path == "/api/speaker/test":
                    if ctx.core.state.value in ("ringing", "snoozed"):
                        _send(self, 409, {"error": "Alarm actief; test niet mogelijk."})
                        return
                    ctx.core.sound_start()
                    time.sleep(SPEAKER_TEST_SECONDS)
                    ctx.core.sound_stop()
                    _send(self, 200, {"ok": True, "sound": ctx.settings.alarm.sound,
                                      "seconds": SPEAKER_TEST_SECONDS})
                elif path == "/api/agenda/auth/start":
                    provider_id = ctx.settings.agenda.provider
                    try:
                        info = get_provider_info(provider_id)
                    except ValueError as exc:
                        _send(self, 400, {"error": str(exc)})
                        return
                    if provider_id == "myx":
                        if ctx.myx_auth is None:
                            _send(self, 503, {"error": "MyX browser-login is niet geconfigureerd."})
                            return
                        started = ctx.myx_auth.start_interactive()
                        _send(self, 202 if started else 409, {
                            "ok": started,
                            "started": started,
                            "message": (
                                "MyX-login is geopend op het scherm van de wekker."
                                if started else "Er loopt al een MyX-login."
                            ),
                        })
                        return
                    if info.auth == "none":
                        _send(self, 409, {"error": "Deze provider heeft geen login nodig."})
                        return
                    if not info.available or provider_id not in ctx.auth.providers:
                        _send(self, 501, {
                            "error": f"Voor {info.display_name} is nog geen "
                                     "login beschikbaar.",
                        })
                        return
                    flow = ctx.auth.start_flow(provider_id, self._base_url())
                    _send(self, 200, {
                        "ok": True,
                        "auth_url": flow.auth_url,
                        "expires_at": flow.expires_at.isoformat(),
                    })
                elif path == "/api/agenda/auth/callback":
                    state = body.get("state", "")
                    if not _valid_state(state):
                        _send(self, 400, {"error": "Ongeldige of ontbrekende state."})
                        return
                    try:
                        link = ctx.auth.complete_flow(ctx.settings.agenda.provider, state)
                    except AuthError as exc:
                        _send(self, 400, {"error": str(exc)})
                        return
                    _send(self, 200, {"ok": True, "account": link.account_label,
                                      "demo": link.demo})
                elif path == "/api/agenda/auth/disconnect":
                    if ctx.settings.agenda.provider == "myx" and ctx.myx_auth is not None:
                        try:
                            had = ctx.myx_auth.disconnect(clear_browser_session=True)
                        except MyXAuthError as exc:
                            _send(self, 409, {"error": str(exc)})
                            return
                        _send(self, 200, {"ok": True, "was_linked": had})
                        return
                    had = ctx.auth.disconnect(ctx.settings.agenda.provider)
                    _send(self, 200, {"ok": True, "was_linked": had})
                else:
                    _send(self, 404, {"error": "Onbekend endpoint"})
            except (SettingsError, ValueError) as exc:
                _send(self, 400, {"error": str(exc)})
            except BodyTooLargeError as exc:
                _send(self, 413, {"error": str(exc)})
            except Exception as exc:  # pragma: no cover - defensief
                log.exception("POST %s faalde", path)
                _send(self, 500, {"error": f"Interne fout: {type(exc).__name__}"})

        def do_PUT(self) -> None:
            # Alias voor POST /api/settings (oudere clients); canoniek is POST.
            path = urlparse(self.path).path
            try:
                if not self._logged_in():
                    _send(self, 401, {"error": "Inloggen vereist."})
                    return
                if path != "/api/settings":
                    _send(self, 404, {"error": "Onbekend endpoint"})
                    return
                _send(self, 200, _apply_settings(ctx, self._read_json()))
            except (SettingsError, ValueError) as exc:
                _send(self, 400, {"error": str(exc)})
            except BodyTooLargeError as exc:
                _send(self, 413, {"error": str(exc)})
            except Exception as exc:  # pragma: no cover - defensief
                log.exception("PUT %s faalde", path)
                _send(self, 500, {"error": f"Interne fout: {type(exc).__name__}"})

    return Handler


def serve_forever(ctx: AppContext, host: str = "127.0.0.1", port: int = 8080) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(ctx))
    thread = threading.Thread(target=server.serve_forever, name="setup-api", daemon=True)
    thread.start()
    log.info("setup-API op http://%s:%d", host, server.server_port)
    return server
