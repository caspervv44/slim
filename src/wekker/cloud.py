"""Veilige cloud-opslag voor niet-geheime wekkerinstellingen.

De Raspberry Pi gebruikt een afzonderlijke device key voor de API. Het
gebruikerswachtwoord wordt alleen gebruikt op de beheerwebsite en wordt nooit
naar de Pi teruggestuurd nadat het daar is gewijzigd.

MyX-feedlinks, Bearer-tokens en andere agenda-geheimen worden bewust NIET
gesynchroniseerd.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from wekker.storage import JsonStore

log = logging.getLogger(__name__)

DEFAULT_CLOUD_URL = "https://veendomain.nl/klok/test2.pl"
SYNC_INTERVAL_SECONDS = 30
HTTP_TIMEOUT_SECONDS = 8
MAX_RESPONSE_BYTES = 128 * 1024


class CloudError(RuntimeError):
    """Cloudverbinding of protocolfout."""


def cloud_settings(settings: Any) -> dict[str, Any]:
    """Alleen instellingen die veilig en nuttig zijn om extern te bewaren."""
    data = settings.to_dict()
    return {
        "alarm": data["alarm"],
        "lamp": data["lamp"],
        "display": data["display"],
        "locale": data["locale"],
    }


def _digest(data: dict[str, Any]) -> str:
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CloudDisplayInfo:
    ready: bool = False
    management_url: str = ""
    username: str = "basis"
    initial_password: str = ""
    password_changed: bool = False
    status: str = "Cloudkoppeling voorbereiden…"
    error: str = ""


class CloudSettingsManager:
    """Asynchrone synchronisatie zodat het touchscreen nooit op internet wacht."""

    def __init__(
        self,
        base_url: str = DEFAULT_CLOUD_URL,
        state_path: str | Path = ".wekker-cloud.json",
        *,
        interval_seconds: int = SYNC_INTERVAL_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("?")
        self.store = JsonStore(state_path)
        self.interval_seconds = max(10, int(interval_seconds))
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._pending: dict[str, Any] | None = None
        self._next_sync = 0.0
        self._status = "Cloudkoppeling voorbereiden…"
        self._error = ""

    def _load_state(self) -> dict[str, Any]:
        try:
            return self.store.load() or {}
        except Exception as exc:
            raise CloudError(f"cloudstatus kon niet worden gelezen: {exc}") from exc

    def _save_state(self, state: dict[str, Any]) -> None:
        self.store.save(state)
        try:
            os.chmod(self.store.path, 0o600)
        except OSError:
            pass

    def display_info(self) -> CloudDisplayInfo:
        try:
            state = self._load_state()
        except CloudError as exc:
            return CloudDisplayInfo(status="Cloudkoppeling niet beschikbaar", error=str(exc))
        ready = bool(state.get("device_id") and state.get("device_key"))
        with self._lock:
            status, error = self._status, self._error
        return CloudDisplayInfo(
            ready=ready,
            management_url=str(state.get("management_url", "")),
            username=str(state.get("username", "basis")),
            initial_password=str(state.get("initial_password", "")),
            password_changed=bool(state.get("password_changed", False)),
            status=status if ready or error else "Cloudkoppeling voorbereiden…",
            error=error,
        )

    def maybe_sync(self, settings: Any) -> None:
        now = time.monotonic()
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            if now < self._next_sync:
                return
            self._next_sync = now + self.interval_seconds
            snapshot = cloud_settings(settings)
            self._worker = threading.Thread(
                target=self._sync_worker,
                args=(snapshot,),
                name="wekker-cloud-sync",
                daemon=True,
            )
            self._worker.start()

    def consume_remote_patch(self) -> dict[str, Any] | None:
        with self._lock:
            patch = self._pending
            self._pending = None
            return patch

    def sync_now_for_test(self, settings: Any) -> None:
        """Synchrone variant voor tests en diagnose, niet voor de GUI-thread."""
        self._sync_worker(cloud_settings(settings))

    def _json_request(
        self,
        action: str,
        payload: dict[str, Any],
        *,
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = json.dumps({"action": action, **payload}, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AventusWekker/0.2",
        }
        if state and state.get("device_id") and state.get("device_key"):
            headers["X-Wekker-Device"] = str(state["device_id"])
            headers["X-Wekker-Key"] = str(state["device_key"])
        req = Request(self.base_url, data=body, headers=headers, method="POST")
        try:
            with urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                raw = resp.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise CloudError("cloudresponse is onverwacht groot")
        except HTTPError as exc:
            try:
                detail = exc.read(4096).decode("utf-8", "replace")
                parsed = json.loads(detail)
                message = parsed.get("error") or f"HTTP {exc.code}"
            except Exception:
                message = f"HTTP {exc.code}"
            raise CloudError(message) from exc
        except (URLError, OSError) as exc:
            raise CloudError(f"cloud niet bereikbaar: {exc}") from exc

        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CloudError("cloud gaf geen geldige JSON terug") from exc
        if not isinstance(data, dict) or not data.get("ok"):
            raise CloudError(str(data.get("error", "onbekende cloudfout")))
        return data

    def _sync_worker(self, local: dict[str, Any]) -> None:
        try:
            state = self._load_state()
            if not state.get("device_id") or not state.get("device_key"):
                reply = self._json_request("register", {"settings": local})
                state = {
                    "device_id": reply["device_id"],
                    "device_key": reply["device_key"],
                    "management_url": reply["management_url"],
                    "username": reply.get("username", "basis"),
                    # Alleen het eenmalige startwachtwoord staat lokaal zodat
                    # het op het fysieke scherm kan worden getoond.
                    "initial_password": reply.get("initial_password", ""),
                    "password_changed": False,
                    "revision": int(reply.get("revision", 1)),
                    "last_synced_hash": _digest(local),
                }
                self._save_state(state)
                with self._lock:
                    self._status = "Online beheer is klaar"
                    self._error = ""
                return

            remote = self._json_request("pull", {}, state=state)
            remote_settings = remote.get("settings")
            if not isinstance(remote_settings, dict):
                raise CloudError("cloudsettings hebben een ongeldig formaat")

            revision = int(remote.get("revision", 0))
            state["password_changed"] = bool(remote.get("password_changed", False))
            local_hash = _digest(local)
            last_hash = str(state.get("last_synced_hash", ""))
            local_revision = int(state.get("revision", 0))

            if revision > local_revision:
                with self._lock:
                    self._pending = remote_settings
                state["revision"] = revision
                state["last_synced_hash"] = _digest(remote_settings)
            elif local_hash != last_hash:
                pushed = self._json_request(
                    "push",
                    {"settings": local, "expected_revision": revision},
                    state=state,
                )
                state["revision"] = int(pushed["revision"])
                state["last_synced_hash"] = local_hash

            self._save_state(state)
            with self._lock:
                self._status = "Gesynchroniseerd"
                self._error = ""
        except Exception as exc:
            log.warning("cloudsync mislukt: %s", exc)
            with self._lock:
                self._status = "Cloud tijdelijk niet bereikbaar"
                self._error = str(exc)
