"""Lokale setup-API op basis van de standaardbibliotheek.

Bewuste keuze: geen Flask/FastAPI, zodat de Pi geen extra dependencies nodig
heeft en de wekker ook zonder telefoon zelfstandig blijft werken. De API is
alleen een dunne schil over core/settings/agenda/button-controller; alle
logica leeft elders.

Eerste prototype (geen motor-, wiel- of touch-endpoints):

  GET  /api/status          toestand, tijd, volgend alarm, lamp, speaker
  GET  /api/settings        huidige instellingen
  POST /api/settings        gedeeltelijke update, bv. {"alarm": {"time": "07:00"}}
  GET  /api/agenda/status   syncstatus + beschikbare providers
  GET  /api/agenda/items    lessen van vandaag (alleen mock; anders 501)
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
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from wekker.agenda.cache import AgendaCache
from wekker.agenda.providers import create_provider_or_error
from wekker.agenda.sync import AgendaSyncService
from wekker.alarm.core import AlarmClock
from wekker.button.controller import ButtonController
from wekker.clock import Clock
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
</style>
</head><body>
<h1>Wekker setup</h1>
<p>De wekker werkt zelfstandig; deze pagina is alleen voor instellen. Lokaal prototype zonder inlog.</p>
<div class="row"><button class="primary" onclick="ping()">Verbinding testen</button><span id="ping"></span></div>

<h2>Status</h2>
<div class="card" id="status">laden…</div>

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

<h2>Agenda (voorbeeldgegevens)</h2>
<div id="agenda">laden…</div>

<script>
const $=id=>document.getElementById(id);
async function jget(u){const r=await fetch(u);const b=await r.json();if(!r.ok)throw new Error(b.error||r.status);return b}
async function jpost(u,b){const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})});const d=await r.json();if(!r.ok)throw new Error(d.error||r.status);return d}
async function ping(){try{await jget('/api/status');$('ping').textContent='✓ verbonden'}catch(e){$('ping').textContent='✗ '+e}}
async function load(){
 try{
  const s=await jget('/api/status');
  $('status').innerHTML='Toestand: <b>'+s.state+'</b><br>Tijd: '+s.now.slice(11,19)
   +'<br>Volgend alarm: '+(s.next_alarm?s.next_alarm.slice(0,16).replace('T',' '):'uit')
   +'<br>Lamp: '+(s.lamp_on?'aan':'uit')+' · Speaker: '+(s.speaker_playing?'aan':'uit');
  const c=await jget('/api/settings');
  $('settings').textContent=JSON.stringify(c,null,1);
  $('f_time').value=c.alarm.time;$('f_lampdur').value=c.lamp.duration_after_button;
  $('f_spk').checked=c.alarm.speaker_enabled;$('f_lamp').checked=c.lamp.on_with_alarm;
  $('f_sound').value=c.alarm.sound;
  const prov=$('f_prov');prov.innerHTML='';
  (c._providers||['mock']).forEach(p=>{const o=document.createElement('option');o.value=p;o.textContent=p+(p==='mock'?' (voorbeeld)':' (nog niet beschikbaar)');if(p===c.agenda.provider)o.selected=true;prov.appendChild(o)});
  try{
   const a=await jget('/api/agenda/items');
   $('agenda').innerHTML=(a.simulated?'<span class="badge">gesimuleerd (mock)</span> ':'')
    +'<table>'+a.items.map(i=>'<tr><td>'+i.start_time.slice(11,16)+'</td><td>'+i.subject+'</td><td>'+i.location+'</td></tr>').join('')+'</table>';
  }catch(e){$('agenda').textContent='Agenda: '+e}
 }catch(e){$('status').textContent='Fout: '+e}
}
async function act(u,b){try{await jpost(u,b)}catch(e){alert(e)}load()}
async function save(){
 const body={alarm:{time:$('f_time').value,speaker_enabled:$('f_spk').checked,sound:$('f_sound').value},
  lamp:{duration_after_button:parseInt($('f_lampdur').value,10),on_with_alarm:$('f_lamp').checked},
  agenda:{provider:$('f_prov').value}};
 try{await jpost('/api/settings',body)}catch(e){alert(e)}load();
}
load();setInterval(load,3000);
</script></body></html>"""


def _send(handler: BaseHTTPRequestHandler, code: int, payload: object) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _apply_settings(ctx: AppContext, patch: dict) -> dict:
    """Valideer, activeer en bewaar nieuwe instellingen. Geeft dict terug."""
    nieuwe = ctx.settings.update_from_dict(patch)
    ctx.settings = nieuwe
    ctx.core.update_settings(nieuwe)
    ctx.display.update_settings(nieuwe)
    ctx.button.update_settings(nieuwe)
    # Providerwissel: bouw de passende adapter (alleen mock werkt echt).
    ctx.sync = AgendaSyncService(create_provider_or_error(nieuwe.agenda.provider),
                                 ctx.cache, ctx.clock)
    try:
        ctx.store.save(nieuwe.to_dict())
    except StorageError as exc:
        log.warning("opslaan mislukt (instellingen wel actief): %s", exc)
        return {**nieuwe.to_dict(), "warning": str(exc)}
    return nieuwe.to_dict()


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
            return data

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            try:
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
                    data["connected"] = ctx.sync.provider_name == "mock"
                    data["stale"] = ctx.cache.is_stale(ctx.clock.now())
                    _send(self, 200, data)
                elif path == "/api/agenda/items":
                    if ctx.sync.provider_name != "mock":
                        _send(self, 501, {
                            "error": f"Provider {ctx.sync.provider_name!r} nog niet "
                                     "beschikbaar; kies 'mock' voor voorbeeldgegevens.",
                        })
                        return
                    lessen = ctx.cache.get_day(ctx.clock.now().date())
                    _send(self, 200, {
                        "simulated": True,
                        "provider": "mock",
                        "items": [les.to_dict() for les in lessen],
                    })
                else:
                    _send(self, 404, {"error": "Onbekend endpoint"})
            except Exception as exc:  # pragma: no cover - defensief
                log.exception("GET %s faalde", path)
                _send(self, 500, {"error": f"Interne fout: {type(exc).__name__}"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                body = self._read_json()
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
