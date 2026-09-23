"""Veilige MyX-login voor de Raspberry Pi via een blijvend Chromium-profiel.

De student logt uitsluitend in op de officiële MyX/Aventus-pagina. De wekker
leest daarna het tijdelijke MyX access-token uit de browsernavigatie/netwerklaag
en bewaart het lokaal met beperkte bestandsrechten. Het schoolwachtwoord wordt
nooit door de wekker gelezen of opgeslagen.

Een blijvend Chromium-profiel bewaart de door MyX/SSO ingestelde sessie. Als een
access-token verloopt, kan een korte headless browsersessie daardoor vaak
automatisch een nieuw token verkrijgen. Als de school-SSO zelf opnieuw om
inloggen vraagt, meldt de wekker dat menselijke login nodig is.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import shutil
import socket
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

MYX_ORIGIN = "https://aventus.myx.nl"
DEFAULT_LOGIN_TIMEOUT_SECONDS = 5 * 60
DEFAULT_SILENT_TIMEOUT_SECONDS = 45
REFRESH_MARGIN_SECONDS = 15 * 60


class MyXAuthError(Exception):
    """MyX-koppeling of tokenvernieuwing is mislukt."""


class MyXFeedError(MyXAuthError):
    """Ongeldige of onbruikbare MyX-feedkoppeling."""


def normalize_feed_url(value: str) -> str:
    """Valideer een door MyX gemaakte webcal/https-feed en normaliseer naar HTTPS.

    De URL zelf functioneert als een geheim abonnementstoken. Daarom accepteren
    we uitsluitend het officiële Aventus MyX-domein en het bekende feedpad.
    """
    if not isinstance(value, str):
        raise MyXFeedError("MyX-feedlink moet tekst zijn.")
    raw = value.strip()
    if not raw:
        raise MyXFeedError("Plak eerst de MyX-feedlink.")
    if raw.lower().startswith("webcal://"):
        raw = "https://" + raw[9:]
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError as exc:
        raise MyXFeedError("De MyX-feedlink is ongeldig.") from exc
    if parsed.scheme != "https" or parsed.hostname != "aventus.myx.nl":
        raise MyXFeedError("Gebruik alleen een feedlink van aventus.myx.nl.")
    delen = [d for d in parsed.path.split("/") if d]
    if len(delen) != 5 or delen[:3] != ["api", "InternetCalendar", "feed"]:
        raise MyXFeedError("Dit lijkt niet op een MyX InternetCalendar-feed.")
    try:
        import uuid
        uuid.UUID(delen[3])
        uuid.UUID(delen[4])
    except (ValueError, AttributeError) as exc:
        raise MyXFeedError("De MyX-feedlink bevat ongeldige identifiers.") from exc
    # Query/fragment horen niet bij de door MyX gegenereerde feed.
    return urllib.parse.urlunsplit(("https", "aventus.myx.nl", parsed.path, "", ""))


class MyXFeedStore:
    """Bewaar alleen de permanente MyX-feedlink, met beperkte bestandsrechten."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else _default_data_dir() / "myx-feed.json"

    def load(self) -> str | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return normalize_feed_url(data["feed_url"])
        except (OSError, KeyError, TypeError, json.JSONDecodeError, MyXFeedError) as exc:
            raise MyXFeedError("Opgeslagen MyX-feed is onleesbaar.") from exc

    def save(self, feed_url: str) -> str:
        url = normalize_feed_url(feed_url)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        tijdelijk = self.path.with_suffix(self.path.suffix + ".tmp")
        inhoud = json.dumps({"feed_url": url}, indent=2, ensure_ascii=False)
        fd = os.open(tijdelijk, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(inhoud)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tijdelijk, self.path)
            os.chmod(self.path, 0o600)
        finally:
            try:
                tijdelijk.unlink(missing_ok=True)
            except OSError:
                pass
        return url

    def clear(self) -> bool:
        bestond = self.path.exists()
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise MyXFeedError("MyX-feedbestand kon niet worden verwijderd.") from exc
        return bestond


def _default_data_dir() -> Path:
    basis = os.getenv("XDG_DATA_HOME")
    if basis:
        return Path(basis).expanduser() / "aventus-wekker"
    return Path.home() / ".local" / "share" / "aventus-wekker"


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    """Lees alleen JWT-metadata.

    Dit verifieert bewust geen handtekening. Het token is al via HTTPS uit de
    officiële MyX-browserflow verkregen; de payload wordt alleen gebruikt voor
    `exp` en `atnId`, niet als zelfstandig bewijs van identiteit.
    """
    delen = token.split(".")
    if len(delen) != 3:
        raise MyXAuthError("MyX gaf geen herkenbaar JWT access-token.")
    try:
        payload = delen[1] + "=" * (-len(delen[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise MyXAuthError("MyX-token bevat onleesbare metadata.") from exc
    if not isinstance(data, dict):
        raise MyXAuthError("MyX-token bevat ongeldige metadata.")
    return data


def _strip_auth_prefix(value: str) -> str:
    waarde = value.strip()
    if waarde.lower().startswith("bearer "):
        return waarde[7:].strip()
    return waarde


@dataclass(frozen=True)
class MyXCredentials:
    access_token: str
    attendee_id: str
    expires_at: datetime
    account_label: str = "Aventus-student"

    @classmethod
    def from_token(cls, token: str) -> "MyXCredentials":
        token = _strip_auth_prefix(token)
        payload = _decode_jwt_payload(token)
        try:
            exp = int(payload["exp"])
            attendee_id = str(payload["atnId"]).strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise MyXAuthError("MyX-token mist exp of atnId.") from exc
        if not attendee_id:
            raise MyXAuthError("MyX-token bevat geen attendee-id.")
        try:
            expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise MyXAuthError("MyX-token heeft een ongeldige vervaldatum.") from exc

        # Toon hooguit een vriendelijke naam; het token zelf komt nooit in logs/UI.
        naam = payload.get("name")
        account_label = str(naam).strip() if isinstance(naam, str) and naam.strip() else "Aventus-student"
        return cls(token, attendee_id, expires_at, account_label)

    def valid_for(self, seconds: int = 0, now: datetime | None = None) -> bool:
        moment = now or datetime.now(timezone.utc)
        return self.expires_at.timestamp() - moment.timestamp() > seconds

    def to_storage_dict(self) -> dict[str, str]:
        return {
            "access_token": self.access_token,
            "attendee_id": self.attendee_id,
            "expires_at": self.expires_at.isoformat(),
            "account_label": self.account_label,
        }


class MyXCredentialStore:
    """Kleine lokale secret-store met 0600-permissies.

    Dit voorkomt per ongeluk meelezen door andere Unix-gebruikers. Het is geen
    hardware-backed kluis; voor een gestolen SD-kaart is schijfversleuteling de
    aangewezen extra beveiligingslaag.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else _default_data_dir() / "myx-auth.json"

    def load(self) -> MyXCredentials | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            token = data["access_token"]
            creds = MyXCredentials.from_token(token)
        except (OSError, KeyError, TypeError, json.JSONDecodeError, MyXAuthError) as exc:
            raise MyXAuthError("Opgeslagen MyX-koppeling is onleesbaar.") from exc
        # De JWT is bron van waarheid voor id/expiry; label mag uit opslag komen.
        label = data.get("account_label")
        if isinstance(label, str) and label.strip():
            creds = MyXCredentials(
                creds.access_token, creds.attendee_id, creds.expires_at, label.strip()
            )
        return creds

    def save(self, credentials: MyXCredentials) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        tijdelijk = self.path.with_suffix(self.path.suffix + ".tmp")
        inhoud = json.dumps(credentials.to_storage_dict(), indent=2, ensure_ascii=False)
        fd = os.open(tijdelijk, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(inhoud)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tijdelijk, self.path)
            os.chmod(self.path, 0o600)
        finally:
            try:
                tijdelijk.unlink(missing_ok=True)
            except OSError:
                pass

    def clear(self) -> bool:
        bestond = self.path.exists()
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise MyXAuthError("MyX-tokenbestand kon niet worden verwijderd.") from exc
        return bestond


class _WebSocket:
    """Minimale RFC 6455-client, alleen wat Chrome DevTools Protocol vereist."""

    def __init__(self, url: str, timeout: float = 2.0) -> None:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "ws" or not parsed.hostname:
            raise MyXAuthError("Chromium gaf een ongeldige DevTools-URL.")
        self._sock = socket.create_connection((parsed.hostname, parsed.port or 80), timeout)
        self._sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        pad = parsed.path or "/"
        if parsed.query:
            pad += "?" + parsed.query
        request = (
            f"GET {pad} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}:{parsed.port or 80}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._sock.sendall(request.encode("ascii"))
        response = self._read_http_headers()
        eerste = response.split(b"\r\n", 1)[0]
        if b" 101 " not in eerste:
            self.close()
            raise MyXAuthError("Chromium DevTools WebSocket kon niet worden geopend.")
        verwachte = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        )
        headers = {}
        for regel in response.split(b"\r\n")[1:]:
            if b":" in regel:
                k, v = regel.split(b":", 1)
                headers[k.strip().lower()] = v.strip()
        if headers.get(b"sec-websocket-accept") != verwachte:
            self.close()
            raise MyXAuthError("Chromium DevTools WebSocket-handshake is ongeldig.")

    def _read_http_headers(self) -> bytes:
        data = bytearray()
        while b"\r\n\r\n" not in data:
            stuk = self._sock.recv(4096)
            if not stuk:
                break
            data.extend(stuk)
            if len(data) > 64 * 1024:
                raise MyXAuthError("Te grote Chromium handshake-response.")
        return bytes(data).split(b"\r\n\r\n", 1)[0]

    def _read_exact(self, n: int) -> bytes:
        data = bytearray()
        while len(data) < n:
            stuk = self._sock.recv(n - len(data))
            if not stuk:
                raise EOFError
            data.extend(stuk)
        return bytes(data)

    def send_json(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data, separators=(",", ":")).encode("utf-8")
        mask = os.urandom(4)
        eerste = bytes([0x81])
        lengte = len(payload)
        if lengte < 126:
            header = eerste + bytes([0x80 | lengte])
        elif lengte <= 0xFFFF:
            header = eerste + bytes([0x80 | 126]) + struct.pack("!H", lengte)
        else:
            header = eerste + bytes([0x80 | 127]) + struct.pack("!Q", lengte)
        gemaskeerd = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(header + mask + gemaskeerd)

    def recv_json(self) -> dict[str, Any] | None:
        while True:
            head = self._read_exact(2)
            opcode = head[0] & 0x0F
            masked = bool(head[1] & 0x80)
            lengte = head[1] & 0x7F
            if lengte == 126:
                lengte = struct.unpack("!H", self._read_exact(2))[0]
            elif lengte == 127:
                lengte = struct.unpack("!Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if masked else b""
            payload = self._read_exact(lengte)
            if masked:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x8:
                return None
            if opcode == 0x9:  # ping -> pong
                self._send_control(0xA, payload)
                continue
            if opcode != 0x1:
                continue
            try:
                obj = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            return obj if isinstance(obj, dict) else None

    def _send_control(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        gemaskeerd = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(bytes([0x80 | opcode, 0x80 | len(payload)]) + mask + gemaskeerd)

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


def _find_chromium() -> str:
    override = os.getenv("WEKKER_CHROMIUM_BIN", "").strip()
    kandidaten = [override] if override else []
    kandidaten += ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable"]
    for naam in kandidaten:
        if naam and shutil.which(naam):
            return shutil.which(naam) or naam
    raise MyXAuthError(
        "Chromium is niet gevonden. Installeer op Raspberry Pi OS: sudo apt install chromium"
    )


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _devtools_targets(port: int) -> list[dict[str, Any]]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _token_from_target_url(url: str) -> str | None:
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.hostname != "aventus.myx.nl":
        return None
    token = urllib.parse.parse_qs(parsed.query).get("token", [None])[0]
    if not isinstance(token, str) or not token:
        return None
    try:
        MyXCredentials.from_token(token)
    except MyXAuthError:
        return None
    return token


def _authorization_from_headers(headers: Any) -> str | None:
    if not isinstance(headers, dict):
        return None
    for key, value in headers.items():
        if str(key).casefold() == "authorization" and isinstance(value, str):
            kandidaat = _strip_auth_prefix(value)
            try:
                MyXCredentials.from_token(kandidaat)
            except MyXAuthError:
                return None
            return kandidaat
    return None


def _capture_token_from_chromium(
    process: subprocess.Popen,
    port: int,
    timeout_seconds: int,
    *,
    require_fresh_seconds: int = 0,
) -> MyXCredentials:
    """Wacht op een MyX-JWT in de URL of in officiële MyX API-requests."""
    deadline = time.monotonic() + timeout_seconds
    websocket: _WebSocket | None = None
    enabled = False
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise MyXAuthError("Chromium is gesloten voordat MyX gekoppeld was.")

        targets = _devtools_targets(port)
        for target in targets:
            target_url = str(target.get("url", ""))
            token = _token_from_target_url(target_url)
            if token:
                creds = MyXCredentials.from_token(token)
                if creds.valid_for(require_fresh_seconds):
                    return creds

        if websocket is None:
            pagina = next(
                (t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")),
                None,
            )
            if pagina:
                try:
                    websocket = _WebSocket(str(pagina["webSocketDebuggerUrl"]))
                    # Eerst network-events aanzetten, daarna pas naar MyX
                    # navigeren. Zo missen we ook bij een snelle stille refresh
                    # geen Authorization-header.
                    websocket.send_json({"id": 1, "method": "Network.enable"})
                    websocket.send_json({"id": 2, "method": "Page.enable"})
                    websocket.send_json({
                        "id": 3,
                        "method": "Page.navigate",
                        "params": {"url": MYX_ORIGIN + "/"},
                    })
                    enabled = True
                except (OSError, MyXAuthError):
                    if websocket:
                        websocket.close()
                    websocket = None

        if websocket is not None and enabled:
            try:
                event = websocket.recv_json()
            except socket.timeout:
                event = None
            except (OSError, EOFError):
                websocket.close()
                websocket = None
                continue
            if event:
                methode = event.get("method")
                params = event.get("params", {})
                headers = None
                request_url = ""
                if methode == "Network.requestWillBeSent":
                    request = params.get("request", {})
                    headers = request.get("headers")
                    request_url = str(request.get("url", ""))
                elif methode == "Network.requestWillBeSentExtraInfo":
                    headers = params.get("headers")
                    # ExtraInfo bevat niet altijd de URL. Een JWT in deze
                    # browser is alleen bruikbaar nadat de gebruiker via ons
                    # vaste MyX-origin is gestart; parse/expiry blijft verplicht.
                token = _authorization_from_headers(headers)
                if token and (not request_url or urllib.parse.urlsplit(request_url).hostname == "aventus.myx.nl"):
                    creds = MyXCredentials.from_token(token)
                    if creds.valid_for(require_fresh_seconds):
                        if websocket:
                            websocket.close()
                        return creds
        else:
            time.sleep(0.15)

    if websocket:
        websocket.close()
    raise MyXAuthError("MyX-login duurde te lang of leverde geen bruikbaar token op.")


class MyXAuthManager:
    """Beheert MyX-token + blijvende Chromium-SSO-sessie."""

    def __init__(
        self,
        *,
        store: MyXCredentialStore | None = None,
        feed_store: MyXFeedStore | None = None,
        profile_dir: str | Path | None = None,
        chromium_bin: str | None = None,
    ) -> None:
        self.store = store or MyXCredentialStore()
        # Bij tests/portable installaties met een custom tokenstore hoort de
        # feed in dezelfde map te blijven in plaats van stil naar $HOME te gaan.
        self.feed_store = feed_store or MyXFeedStore(
            self.store.path.parent / "myx-feed.json"
            if store is not None
            else None
        )
        self.profile_dir = (
            Path(profile_dir)
            if profile_dir is not None
            else _default_data_dir() / "myx-browser"
        )
        self._chromium_bin = chromium_bin
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._state = "idle"
        self._last_error = ""

    def _browser_binary(self) -> str:
        if self._chromium_bin:
            if not shutil.which(self._chromium_bin) and not Path(self._chromium_bin).exists():
                raise MyXAuthError(f"Chromium bestaat niet: {self._chromium_bin}")
            return self._chromium_bin
        return _find_chromium()

    def credentials(self) -> MyXCredentials | None:
        try:
            return self.store.load()
        except MyXAuthError:
            return None

    def status(self) -> dict[str, Any]:
        creds = self.credentials()
        with self._lock:
            state = self._state
            error = self._last_error
            busy = bool(self._worker and self._worker.is_alive())
        try:
            feed_url = self.feed_store.load()
        except MyXFeedError:
            feed_url = None
        linked = bool(feed_url or creds)
        token_valid = bool(creds and creds.valid_for())
        return {
            "linked": linked,
            "token_valid": token_valid,
            "feed_configured": bool(feed_url),
            "connection_mode": "feed" if feed_url else ("browser-sso" if creds else None),
            "needs_login": not linked or (not feed_url and not token_valid),
            "account": creds.account_label if creds else None,
            "attendee_id": creds.attendee_id if creds else None,
            "expires_at": creds.expires_at.isoformat() if creds else None,
            "busy": busy,
            "state": state,
            "error": error or None,
            "profile_present": self.profile_dir.exists(),
        }

    def config(self, *, require_valid: bool = True) -> "MyXConfig":
        from wekker.agenda.myx import MyXConfig

        try:
            feed_url = self.feed_store.load()
        except MyXFeedError:
            feed_url = None
        if feed_url:
            return MyXConfig(feed_url=feed_url)
        creds = self.credentials()
        if creds and (creds.valid_for() or not require_valid):
            return MyXConfig(bearer_token=creds.access_token, att_id=creds.attendee_id)
        # Backwards compatible voor development/systemd-installaties die al
        # environment variables gebruiken.
        env = MyXConfig.from_env()
        if env.configured:
            return env
        return MyXConfig()

    def ensure_config(self) -> "MyXConfig":
        """Geef geldige config; probeer vlak voor afloop stil te vernieuwen."""
        from wekker.agenda.myx import MyXConfig

        try:
            feed_url = self.feed_store.load()
        except MyXFeedError as exc:
            raise MyXAuthError(str(exc)) from exc
        if feed_url:
            return MyXConfig(feed_url=feed_url)

        creds = self.credentials()
        if creds and creds.valid_for(REFRESH_MARGIN_SECONDS):
            return MyXConfig(bearer_token=creds.access_token, att_id=creds.attendee_id)
        if self.profile_dir.exists():
            try:
                vernieuwd = self.refresh_silently()
                return MyXConfig(
                    bearer_token=vernieuwd.access_token,
                    att_id=vernieuwd.attendee_id,
                )
            except MyXAuthError as exc:
                # Een nog geldig token blijft bruikbaar als proactieve refresh
                # tijdelijk faalt. Bij echte expiry volgt duidelijke login-fout.
                if creds and creds.valid_for():
                    log.warning("MyX proactieve tokenvernieuwing faalde; huidig token blijft geldig")
                    return MyXConfig(
                        bearer_token=creds.access_token,
                        att_id=creds.attendee_id,
                    )
                raise MyXAuthError(
                    "MyX-sessie is verlopen; log opnieuw in via Instellingen."
                ) from exc
        env = MyXConfig.from_env()
        if env.configured:
            return env
        raise MyXAuthError("MyX is nog niet gekoppeld; open Instellingen → MyX koppelen.")

    def _run_browser(self, *, headless: bool, timeout_seconds: int) -> MyXCredentials:
        self.profile_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.profile_dir, 0o700)
        except OSError:
            pass
        port = _free_local_port()
        args = [
            self._browser_binary(),
            f"--user-data-dir={self.profile_dir}",
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--disable-extensions",
            "--disable-background-networking",
            "--app=about:blank",
        ]
        if headless:
            args.insert(1, "--headless=new")
        # Geen shell=True: login-URL/token kan nooit als shellcode worden gezien.
        try:
            process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise MyXAuthError("Chromium kon niet worden gestart.") from exc
        try:
            fresh = REFRESH_MARGIN_SECONDS if headless else 0
            credentials = _capture_token_from_chromium(
                process, port, timeout_seconds, require_fresh_seconds=fresh
            )
            # Geef MyX nog even tijd om eigen cookies/storage (waaronder de
            # refreshsessie) naar het blijvende Chromium-profiel te flushen.
            # We stoppen de browser pas daarna.
            time.sleep(3 if not headless else 1)
            self.store.save(credentials)
            return credentials
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)

    def login_interactive(self) -> MyXCredentials:
        with self._lock:
            self._state = "waiting_for_login"
            self._last_error = ""
        try:
            credentials = self._run_browser(
                headless=False, timeout_seconds=DEFAULT_LOGIN_TIMEOUT_SECONDS
            )
        except MyXAuthError as exc:
            with self._lock:
                self._state = "login_required"
                self._last_error = str(exc)
            raise
        with self._lock:
            self._state = "linked"
            self._last_error = ""
        return credentials

    def refresh_silently(self) -> MyXCredentials:
        with self._lock:
            self._state = "refreshing"
            self._last_error = ""
        try:
            credentials = self._run_browser(
                headless=True, timeout_seconds=DEFAULT_SILENT_TIMEOUT_SECONDS
            )
        except MyXAuthError as exc:
            with self._lock:
                self._state = "login_required"
                self._last_error = "Opnieuw inloggen bij MyX is nodig."
            raise
        with self._lock:
            self._state = "linked"
            self._last_error = ""
        return credentials

    def start_interactive(self) -> bool:
        """Start de zichtbare login in een achtergrondthread.

        Geeft False als er al een login/refresh bezig is.
        """
        with self._lock:
            if self._worker and self._worker.is_alive():
                return False

            def run() -> None:
                try:
                    self.login_interactive()
                except MyXAuthError:
                    # Status bevat een veilige melding; token/wachtwoord nooit loggen.
                    log.warning("MyX-login niet afgerond")

            self._worker = threading.Thread(target=run, name="myx-login", daemon=True)
            self._worker.start()
            return True

    def disconnect(self, *, clear_browser_session: bool = True) -> bool:
        """Verwijder lokaal token; standaard ook SSO-browserprofiel.

        Ontkoppelen hoort op een gedeelde wekker ook de volgende student niet
        automatisch als de vorige student te laten aanmelden.
        """
        with self._lock:
            if self._worker and self._worker.is_alive():
                raise MyXAuthError("Wacht tot de lopende MyX-login klaar is.")
            had = self.store.clear()
            had_feed = self.feed_store.clear()
            if clear_browser_session and self.profile_dir.exists():
                try:
                    shutil.rmtree(self.profile_dir)
                except OSError as exc:
                    raise MyXAuthError("MyX-browsersessie kon niet worden verwijderd.") from exc
            self._state = "idle"
            self._last_error = ""
            return had or had_feed

    def save_feed(self, feed_url: str) -> str:
        """Koppel MyX via de permanente InternetCalendar-feed."""
        url = self.feed_store.save(feed_url)
        with self._lock:
            self._state = "linked"
            self._last_error = ""
        return url

    def feed_url(self) -> str | None:
        try:
            return self.feed_store.load()
        except MyXFeedError:
            return None
