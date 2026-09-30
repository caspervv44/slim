"""Veilige diagnose-informatie voor het lokale WakeSync-scherm.

Deze module exporteert bewust geen device-key, beheerderswachtwoord of MyX-feed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from wekker import __version__
from wekker.touch_setup import TouchConfigurator


@dataclass(frozen=True)
class DiagnosticSnapshot:
    version: str
    generated_at: str
    timezone: str
    ntp_synchronized: str
    agenda_status: str
    agenda_last_success: str
    agenda_last_attempt: str
    cloud_status: str
    touch: dict[str, Any]
    display_session: str
    display_name: str
    backlight: str
    update_status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _command(args: list[str], timeout: float = 2.0) -> str:
    try:
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
        )
        return (result.stdout or "").strip()
    except Exception:
        return ""


def _ntp_status() -> str:
    raw = _command(["timedatectl", "show", "-p", "NTPSynchronized", "--value"])
    if raw.lower() == "yes":
        return "gesynchroniseerd"
    if raw.lower() == "no":
        return "niet gesynchroniseerd"
    return "onbekend"


def _backlight_status() -> str:
    root = Path("/sys/class/backlight")
    try:
        names = [p.name for p in root.iterdir()]
    except OSError:
        names = []
    if names:
        return "hardware: " + ", ".join(names)
    return "geen echte backlight-driver gedetecteerd"


def _update_status(project_root: Path | None = None) -> str:
    root = project_root or Path.cwd()
    path = root / ".wakesync-update-status.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data.get("status") or "onbekend")
    except Exception:
        return "nog geen update uitgevoerd"


def collect_diagnostics(runtime: Any | None = None) -> DiagnosticSnapshot:
    timezone_name = "onbekend"
    agenda_status = "onbekend"
    last_success = ""
    last_attempt = ""
    cloud_status = "niet actief"

    if runtime is not None:
        ctx = runtime.ctx
        timezone_name = str(getattr(ctx.settings.locale, "timezone", "onbekend"))
        try:
            status = ctx.cache.status_dict()
            agenda_status = str(status.get("status") or "onbekend")
            last_success = str(status.get("last_success") or "")
            last_attempt = str(status.get("last_attempt") or "")
        except Exception:
            pass
        cloud = getattr(ctx, "cloud", None)
        if cloud is not None:
            try:
                cloud_status = str(cloud.display_info().status)
            except Exception:
                cloud_status = "fout"

    try:
        touch = TouchConfigurator().detect().to_dict()
    except Exception as exc:
        touch = {"configured": False, "message": f"diagnosefout: {type(exc).__name__}"}

    output = _command(["wlr-randr"])
    first_output = ""
    for line in output.splitlines():
        if line and not line.startswith((" ", "\t")):
            first_output = line.split()[0]
            break

    return DiagnosticSnapshot(
        version=__version__,
        generated_at=datetime.now(timezone.utc).isoformat(),
        timezone=timezone_name,
        ntp_synchronized=_ntp_status(),
        agenda_status=agenda_status,
        agenda_last_success=last_success,
        agenda_last_attempt=last_attempt,
        cloud_status=cloud_status,
        touch=touch,
        display_session=os.environ.get("XDG_SESSION_TYPE", "onbekend"),
        display_name=first_output or os.environ.get("WAYLAND_DISPLAY", "onbekend"),
        backlight=_backlight_status(),
        update_status=_update_status(),
    )


def export_diagnostics(path: str | Path, runtime: Any | None = None) -> Path:
    """Schrijf veilige diagnose-JSON zonder accountgeheimen."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(collect_diagnostics(runtime).to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target
