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
from typing import Any

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
    # Optionele externe opslag voor veilige, niet-geheime instellingen.
    cloud: Any | None = None


INDEX_HTML = """<!doctype html>
<html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WaveSync</title>
<style>
:root{
  color-scheme:light;--blue:#2563eb;--blue2:#1d4ed8;--ink:#172033;--muted:#657087;
  --line:#e4e8ef;--bg:#f4f7fb;--card:#fff;--green:#16845b;--amber:#a16207;--red:#b42318;
  font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif
}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink)}
header{background:linear-gradient(135deg,#1d4ed8,#3b82f6);color:white;padding:24px 18px}
.header-inner,.wrap{max-width:980px;margin:auto}.brand{font-size:1.45rem;font-weight:800;letter-spacing:-.02em}
.subtitle{margin-top:5px;opacity:.9;font-size:.92rem}.wrap{padding:18px}
.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:16px}.span-4{grid-column:span 4}.span-6{grid-column:span 6}.span-8{grid-column:span 8}.span-12{grid-column:span 12}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px;box-shadow:0 5px 18px rgba(24,39,75,.05)}
.card h2{font-size:1rem;margin:0 0 14px}.eyebrow{font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;font-weight:700}
.metric{font-size:1.55rem;font-weight:750;margin-top:4px}.muted{color:var(--muted)}.small{font-size:.86rem}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.stack{display:grid;gap:12px}
label{display:grid;gap:6px;font-size:.86rem;font-weight:650;color:#3f4a60;flex:1;min-width:150px}
input,select,button{font:inherit;border-radius:10px;border:1px solid #cfd6e2;padding:10px 12px}
input,select{background:#fff;width:100%;color:var(--ink)}button{background:#fff;cursor:pointer;font-weight:650}
button:hover{background:#f8fafc}button.primary{background:var(--blue);border-color:var(--blue);color:#fff}button.primary:hover{background:var(--blue2)}
button.danger{color:var(--red)}button:disabled{opacity:.5;cursor:not-allowed}
.pill{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:5px 9px;font-size:.78rem;font-weight:700;background:#eef2f7;color:#4d596f}
.pill.ok{background:#e8f7f1;color:var(--green)}.pill.warn{background:#fff6df;color:var(--amber)}.pill.bad{background:#feeceb;color:var(--red)}
.dot{width:7px;height:7px;border-radius:50%;background:currentColor}.divider{height:1px;background:var(--line);margin:14px 0}
.help{background:#f7f9fc;border:1px solid var(--line);border-radius:12px;padding:13px;font-size:.88rem;line-height:1.5}
.steps{margin:8px 0 0;padding-left:20px}.steps li{margin:5px 0}
.feed-box{display:grid;grid-template-columns:1fr auto;gap:8px}.feed-box input{min-width:0}
#error{position:sticky;top:8px;z-index:20;display:none;background:#fff0ef;color:var(--red);border:1px solid #fecaca;padding:11px 14px;border-radius:10px;margin-bottom:12px}
#success{display:none;background:#ebf8f2;color:var(--green);border:1px solid #b7e4cf;padding:11px 14px;border-radius:10px;margin-bottom:12px}
.agenda-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:12px}
.day{border-top:1px solid var(--line);padding:14px 0}.day:first-child{border-top:0;padding-top:0}.day-title{font-weight:750;margin-bottom:9px}
.lesson{display:grid;grid-template-columns:88px 1fr auto;gap:12px;align-items:start;padding:11px 12px;background:#f8fafe;border:1px solid #e8edf5;border-radius:12px;margin:7px 0}
.time{font-weight:800;color:var(--blue)}.subject{font-weight:750}.meta{font-size:.82rem;color:var(--muted);margin-top:3px}.room{font-size:.8rem;font-weight:700;background:#eef3ff;color:#315bbd;padding:5px 8px;border-radius:8px;white-space:nowrap}
.empty{color:var(--muted);font-size:.88rem;padding:6px 0}
details summary{cursor:pointer;font-weight:700}.danger-zone{border-color:#f3d1ce}
pre{white-space:pre-wrap;word-break:break-word;background:#f7f9fc;border-radius:10px;padding:10px;font-size:.78rem}
@media(max-width:760px){.span-4,.span-6,.span-8{grid-column:span 12}.lesson{grid-template-columns:72px 1fr}.room{grid-column:2}.feed-box{grid-template-columns:1fr}.wrap{padding:12px}}
</style></head>
<body>
<header><div class="header-inner"><div class="brand">WaveSync</div>
<div class="subtitle">Instellen en MyX koppelen via je browser — het wekkerdisplay blijft alleen voor de wekker zelf.</div></div></header>
<main class="wrap">
<div id="error"></div><div id="err" style="display:none"></div><div id="success"></div>

<div class="grid">
<section class="card span-4"><div class="eyebrow">Wekker</div><div class="metric" id="st_time">--:--</div>
<div class="small muted">Volgende alarm <b id="st_alarm">–</b> · <span id="st_tz" style="display:none"></span></div><div class="divider"></div>
<div class="row"><span id="state_pill" class="pill"><span class="dot"></span><span id="st_state">laden</span></span>
<span id="conn_pill" class="pill"><span class="dot"></span><span id="st_conn">verbinden…</span></span></div></section>

<section class="card span-4"><div class="eyebrow">Agenda</div><div class="metric" id="st_agenda">–</div>
<div class="small muted" id="st_sync">Nog niet gesynchroniseerd</div><div class="divider"></div>
<button onclick="syncNow()">Nu synchroniseren</button></section>

<section class="card span-4"><div class="eyebrow">Hardware</div>
<div class="row"><span class="pill">Lamp: <b id="st_lamp">–</b></span><span class="pill">Speaker: <b id="st_speaker">–</b></span></div>
<div class="divider"></div><div class="row"><button onclick="act('/api/lamp/test')">Lamp testen</button><button onclick="act('/api/speaker/test')">Speaker testen</button></div></section>

<section class="card span-12">
<div class="agenda-head"><div><div class="eyebrow">Rooster</div><h2 style="margin:3px 0 0">Komende 7 dagen</h2></div>
<span id="agenda_badge" class="pill">laden…</span></div>
<div id="agenda">Rooster laden…</div>
</section>

<section class="card span-8">
<div class="eyebrow">MyX / Xedule</div><h2 style="font-size:1.2rem;margin-top:4px">Rooster koppelen</h2>
<div id="auth_summary" class="help">Status laden…</div>
<div class="divider"></div>
<div class="stack">
<div>
<strong>Aanbevolen: MyX Feed</strong>
<div class="small muted" style="margin-top:4px">De feed is een blijvende agenda-abonnementlink. Daardoor hoeft de wekker niet iedere dag opnieuw in te loggen en is een tijdelijke Bearer-token niet nodig.</div>
</div>
<div class="help">
<b>Feedlink vinden in MyX</b>
<ol class="steps">
<li>Open <b>Mijn rooster</b> in MyX.</li>
<li>Klik links naast “Mijn rooster” op de <b>drie puntjes</b>.</li>
<li>Kies het <b>Feed</b>-icoon.</li>
<li>Kopieer de link die met <code>webcal://aventus.myx.nl/api/InternetCalendar/feed/…</code> begint en plak hem hieronder.</li>
</ol>
</div>
<div class="feed-box"><input id="f_feed" autocomplete="off" spellcheck="false" placeholder="webcal://aventus.myx.nl/api/InternetCalendar/feed/…">
<button class="primary" onclick="saveFeed()">Feed koppelen</button></div>
<div class="small muted">De feedlink wordt alleen lokaal op de Raspberry Pi bewaard. Behandel hem als een geheim: wie de link heeft, kan mogelijk je rooster lezen.</div>
<details><summary>Alternatief: eenmalig inloggen op het Pi-scherm</summary>
<p class="small muted">Als het kopiëren van de Feed-link niet lukt, kan de webpagina de bestaande MyX-browserlogin op het Raspberry Pi-scherm starten. Deze methode gebruikt tijdelijk een Bearer-token en probeert de SSO-sessie te bewaren.</p>
<button onclick="startPiLogin()">MyX-login op Pi starten</button>
</details>
</div></section>

<section class="card span-4">
<div class="eyebrow">Instellingen</div><h2 style="font-size:1.2rem;margin-top:4px">Wekker</h2>
<div class="stack">
<label>Wektijd<input id="f_time" type="time" value="07:30"></label>
<label>Lampduur na knop (seconden)<input id="f_lampdur" type="number" min="1" max="3600" value="30"></label>
<label>Geluid<input id="f_sound" value="beep"></label>
<label><span><input type="checkbox" id="f_spk" style="width:auto"> Speaker bij alarm</span></label>
<label><span><input type="checkbox" id="f_lamp" style="width:auto"> Lamp bij alarm</span></label>
<label>Agenda-provider<select id="f_prov"></select></label>
<button class="primary" onclick="saveSettings()">Instellingen opslaan</button>
</div></section>

<section class="card span-12 danger-zone">
<details><summary>Beheer &amp; geavanceerd</summary>
<div class="row" style="margin-top:12px"><button class="danger" onclick="disconnectAgenda()">MyX-koppeling verwijderen</button><button onclick="ping()">Verbinding testen</button><button onclick="uitloggen()">Uitloggen</button></div>
<pre id="debug_settings" style="display:none"></pre>
</details></section>
</div>
</main>

<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function jget(u){const r=await fetch(u);if(r.status===401){location='/login';throw new Error('login vereist')}const b=await r.json();if(!r.ok)throw new Error(b.error||r.status);return b}
async function jpost(u,b){const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})});if(r.status===401){location='/login';throw new Error('login vereist')}const d=await r.json();if(!r.ok)throw new Error(d.error||r.status);return d}
function msg(text,ok=false){const good=$('success'),bad=$('error');good.style.display='none';bad.style.display='none';const el=ok?good:bad;el.textContent=text;el.style.display='block';setTimeout(()=>{el.style.display='none'},6000)}
function fmtDate(iso){const d=new Date(iso+'T12:00:00');return new Intl.DateTimeFormat('nl-NL',{weekday:'long',day:'numeric',month:'long'}).format(d)}
function fmtTime(iso){return iso?iso.slice(11,16):'--:--'}
function renderAgenda(a){
  $('agenda_badge').textContent=a.simulated?'Voorbeelddata':(a.provider==='myx'?'MyX':'Agenda');
  const days=a.days||[];
  $('agenda').innerHTML=days.map(d=>{
    const items=d.items||[];
    return `<div class="day"><div class="day-title">${esc(fmtDate(d.date))}</div>`+
      (items.length?items.map(i=>`<div class="lesson"><div class="time">${esc(fmtTime(i.start_time))}<div class="small muted">${esc(fmtTime(i.end_time))}</div></div><div><div class="subject">${esc(i.subject)}</div><div class="meta">${i.teacher?'Docent: '+esc(i.teacher):''}</div></div>${i.location?`<div class="room">${esc(i.location)}</div>`:''}</div>`).join(''):`<div class="empty">Geen lessen</div>`)+`</div>`;
  }).join('');
}
function renderAuth(a){
  let h='';
  if(a.provider!=='myx'){h=`Huidige provider: <b>${esc(a.provider_name)}</b>`}
  else if(a.feed_configured){h=`<span class="pill ok"><span class="dot"></span>MyX Feed gekoppeld</span><div class="small muted" style="margin-top:8px">De wekker kan het rooster automatisch ophalen zonder dagelijkse login.</div>`}
  else if(a.linked&&a.token_valid){h=`<span class="pill ok"><span class="dot"></span>MyX gekoppeld</span><div class="small muted" style="margin-top:8px">${esc(a.account||'Aventus-student')} · browser-SSO</div>`}
  else if(a.busy){h=`<span class="pill warn"><span class="dot"></span>Wachten op MyX-login op de Pi…</span>`}
  else{h=`<span class="pill warn"><span class="dot"></span>Nog niet gekoppeld</span><div class="small muted" style="margin-top:8px">Gebruik bij voorkeur de Feed-koppeling hieronder.</div>`}
  if(a.auth_error)h+=`<div class="small" style="color:var(--red);margin-top:7px">${esc(a.auth_error)}</div>`;
  $('auth_summary').innerHTML=h;
}
async function tick(){
 try{
  const [s,a,g]=await Promise.all([jget('/api/status'),jget('/api/agenda/auth/status'),jget('/api/agenda/status')]);
  $('st_time').textContent=s.now.slice(11,16);$('st_tz').textContent=s.timezone;$('st_alarm').textContent=s.next_alarm?fmtTime(s.next_alarm):'uit';$('st_state').textContent=s.state;
  $('st_lamp').textContent=s.lamp_on?'aan':'uit';$('st_speaker').textContent=s.speaker_playing?'aan':'uit';$('st_conn').textContent='verbonden';$('conn_pill').className='pill ok';
  $('st_agenda').textContent=a.provider_name||a.provider;$('st_sync').textContent=g.last_sync?'Bijgewerkt '+g.last_sync.slice(0,16).replace('T',' '):'Nog niet gesynchroniseerd';
  renderAuth(a);
  try{renderAgenda(await jget('/api/agenda/items'))}catch(e){$('agenda').innerHTML=`<div class="empty">${esc(e.message)}</div>`}
 }catch(e){$('st_conn').textContent='offline';$('conn_pill').className='pill bad'}
}
async function fillForm(){
 try{
  const c=await jget('/api/settings');$('f_time').value=c.alarm.time;$('f_lampdur').value=c.lamp.duration_after_button;$('f_spk').checked=c.alarm.speaker_enabled;$('f_lamp').checked=c.lamp.on_with_alarm;$('f_sound').value=c.alarm.sound;
  const plist=await jget('/api/agenda/providers'),sel=$('f_prov');sel.innerHTML='';plist.providers.forEach(p=>{const o=document.createElement('option');o.value=p.id;o.textContent=p.display_name+(p.available?'':' (later)');o.selected=p.selected;sel.appendChild(o)});
 }catch(e){msg('Instellingen laden mislukt: '+e.message)}
}
async function saveSettings(){try{await jpost('/api/settings',{alarm:{time:$('f_time').value,speaker_enabled:$('f_spk').checked,sound:$('f_sound').value},lamp:{duration_after_button:Number($('f_lampdur').value),on_with_alarm:$('f_lamp').checked},agenda:{provider:$('f_prov').value}});msg('Instellingen opgeslagen.',true);await tick()}catch(e){msg(e.message)}}
async function saveFeed(){try{const r=await jpost('/api/agenda/myx/feed',{feed_url:$('f_feed').value});$('f_feed').value='';msg(r.message||'MyX-feed gekoppeld.',true);await fillForm();await tick()}catch(e){msg('Feed koppelen mislukt: '+e.message)}}
async function syncNow(){try{await jpost('/api/agenda/sync',{});msg('Rooster bijgewerkt.',true);await tick()}catch(e){msg('Synchroniseren mislukt: '+e.message)}}
async function startPiLogin(){try{await jpost('/api/settings',{agenda:{provider:'myx'}});const r=await jpost('/api/agenda/auth/start',{});msg(r.message||'MyX-login geopend op de Raspberry Pi.',true);await fillForm();await tick()}catch(e){msg(e.message)}}
async function disconnectAgenda(){if(!confirm('MyX-koppeling en opgeslagen browsersessie verwijderen?'))return;try{await jpost('/api/agenda/auth/disconnect',{});msg('MyX-koppeling verwijderd.',true);await tick()}catch(e){msg(e.message)}}
async function act(u,b){try{await jpost(u,b||{});await tick()}catch(e){msg(e.message)}}
async function ping(){try{await jget('/api/status');msg('Verbinding met de wekker is goed.',true)}catch(e){msg('Geen verbinding: '+e.message)}}
async function uitloggen(){try{await jpost('/api/logout',{})}catch(e){}location='/login'}
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
<h1>WaveSync</h1>
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
    set_timezone = getattr(ctx.clock, "set_timezone", None)
    if callable(set_timezone):
        set_timezone(nieuwe.locale.timezone)
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
        cfg = (
            ctx.myx_auth.config(require_valid=False)
            if ctx.myx_auth is not None
            else MyXConfig.from_env()
        )
        if not cfg.configured:
            _send(handler, 409, {
                "error": "MyX is nog niet gekoppeld. Voeg via deze webpagina de MyX-feed toe.",
                "action": "configure-feed",
            })
            return
    elif provider_id not in ("mock", "osiris"):
        _send(handler, 501, {
            "error": f"Provider {provider_id!r} nog niet "
                     "beschikbaar; kies 'mock' voor voorbeeldgegevens.",
        })
        return
    vandaag = ctx.clock.now().date()
    lessen = ctx.cache.get_day(vandaag)
    dagen = []
    from datetime import timedelta
    for offset in range(7):
        dag = vandaag + timedelta(days=offset)
        dag_lessen = ctx.cache.get_day(dag)
        dagen.append({
            "date": dag.isoformat(),
            "items": [les.to_dict() for les in dag_lessen],
        })
    alle_lessen = [les for dag in dagen for les in dag["items"]]
    _send(handler, 200, {
        "simulated": all(
            les.get("source") in SIMULATED_SOURCES for les in alle_lessen
        ),
        "provider": provider_id,
        "items": [les.to_dict() for les in lessen],
        "days": dagen,
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
                "feed_configured": myx_status.get("feed_configured") if myx_status else False,
                "connection_mode": myx_status.get("connection_mode") if myx_status else None,
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
                elif path == "/api/agenda/myx/feed":
                    if ctx.myx_auth is None:
                        _send(self, 503, {"error": "MyX-koppelservice is niet beschikbaar."})
                        return
                    feed_url = body.get("feed_url", "")
                    try:
                        ctx.myx_auth.save_feed(feed_url)
                        # Selecteer MyX direct: de feed is nu de primaire koppeling.
                        _apply_settings(ctx, {"agenda": {"provider": "myx"}})
                        # Probeer meteen te synchroniseren zodat een foutieve of
                        # ingetrokken feed direct zichtbaar wordt.
                        ok = ctx.sync.sync_default_window()
                    except (MyXAuthError, SettingsError) as exc:
                        _send(self, 400, {"error": str(exc)})
                        return
                    if not ok:
                        _send(self, 502, {
                            "error": ctx.cache.error or "MyX-feed kon niet worden opgehaald."
                        })
                        return
                    _send(self, 200, {"ok": True, "message": "MyX-feed gekoppeld."})
                elif path == "/api/agenda/sync":
                    ok = ctx.sync.sync_default_window()
                    if ok:
                        _send(self, 200, {"ok": True, **ctx.cache.status_dict()})
                    else:
                        _send(self, 502, {
                            "ok": False,
                            "error": ctx.cache.error or "Synchroniseren mislukt.",
                            **ctx.cache.status_dict(),
                        })
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
