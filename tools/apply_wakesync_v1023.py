#!/usr/bin/env python3
"""Veilige update naar WakeSync 10.2.3, zonder instellingen aan te raken."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import uuid

PROJECT = Path(__file__).resolve().parents[1]
PAYLOAD = PROJECT / "updates/v10_2_3/payload"
MANIFEST = PROJECT / "updates/v10_2_3/manifest.json"
EXPECTED_FILES = (
    "src/wekker/__init__.py",
    "src/wekker/gui/app.py",
    "src/wekker/gui/premium.py",
    "src/wekker/gui/premium_render.py",
    "src/wekker/hardware/audio.py",
    "tools/test_wakesync_alarm_audio.py",
    "src/wekker/alarm/sounds.py",
    "src/wekker/hardware/tone_patterns.py",
)


class UpdateError(RuntimeError):
    """Geen wijzigingen bij een onveilige of afwijkende bron."""


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalized_checksum(data: bytes) -> str:
    """Windows-Git kan CRLF gebruiken terwijl Linux LF gebruikt."""
    return checksum(data.replace(b"\r\n", b"\n"))


def safe_path(root: Path, name: str) -> Path:
    parts = Path(name).parts
    if not name or "\\" in name or Path(name).is_absolute() or ".." in parts:
        raise UpdateError(f"Onveilig bestandspad: {name!r}")
    path = root / name
    if not path.resolve().is_relative_to(root.resolve()):
        raise UpdateError(f"Bestand buiten de projectmap: {name}")
    if path.is_symlink():
        raise UpdateError(f"Symbolische koppeling wordt niet gewijzigd: {name}")
    return path


def read_manifest() -> list[dict]:
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UpdateError(f"Updatepakket onvolledig: {exc}") from exc
    files = data.get("files")
    if data.get("release") != "10.2.3" or not isinstance(files, list):
        raise UpdateError("Verkeerd updatepakket.")
    if (len(files) != len(EXPECTED_FILES)
            or not all(isinstance(row, dict) for row in files)
            or [row["path"] for row in files] != list(EXPECTED_FILES)):
        raise UpdateError("De bestandslijst is onjuist.")
    for row in files:
        name = row["path"]
        payload = safe_path(PAYLOAD, name)
        safe_path(PROJECT, name)
        if row.get("base_sha256_lf") is not None and not isinstance(row["base_sha256_lf"], str):
            raise UpdateError(f"Basis-checksum ongeldig: {name}")
        if not payload.is_file() or checksum(payload.read_bytes()) != row.get("payload_sha256"):
            raise UpdateError(f"Payload beschadigd: {name}")
    return files


def updated_project(data: bytes) -> bytes:
    """Wijzig uitsluitend version binnen [project], nooit de afhankelijkheden."""
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UpdateError("pyproject.toml is geen UTF-8.") from exc
    section = re.search(r"(?ms)^\[project\]\s*\r?\n(.*?)(?=^\[|\Z)", content)
    if section is None:
        raise UpdateError("pyproject.toml mist [project].")
    body = section.group(1)
    found = list(re.finditer(r"(?m)^(\s*version\s*=\s*)([\"'])(10\.2\.[23])\2", body))
    if len(found) != 1:
        raise UpdateError("Projectversie moet 10.2.2 of 10.2.3 zijn.")
    match = found[0]
    if match.group(3) == "10.2.3":
        return data
    changed = body[:match.start(3)] + "10.2.3" + body[match.end(3):]
    return (content[:section.start(1)] + changed + content[section.end(1):]).encode("utf-8")


def check_changes() -> dict[str, bytes]:
    """Eerst alles controleren; nog geen bestanden veranderen."""
    changes = {}
    for row in read_manifest():
        name = row["path"]
        current = safe_path(PROJECT, name)
        new = (PAYLOAD / name).read_bytes()
        if current.is_file() and normalized_checksum(current.read_bytes()) == normalized_checksum(new):
            print(f"Al bijgewerkt: {name}")
            continue
        if row["base_sha256_lf"] is None:
            if current.exists():
                raise UpdateError(f"Nieuw bestand heeft andere inhoud: {name}. Niets aangepast.")
            changes[name] = new
        elif current.is_file() and normalized_checksum(current.read_bytes()) == row["base_sha256_lf"]:
            changes[name] = new
        else:
            raise UpdateError(
                f"{name} wijkt af van de gecontroleerde WakeSync 10.2.2. "
                "Niets aangepast; upload het bestand voor een gerichte samenvoeging."
            )
        print(f"Wijziging: {name}")

    project = safe_path(PROJECT, "pyproject.toml")
    if not project.is_file():
        raise UpdateError("pyproject.toml ontbreekt.")
    old = project.read_bytes()
    new = updated_project(old)
    if new != old:
        changes["pyproject.toml"] = new
        print("Wijziging: pyproject.toml (10.2.3)")
    else:
        print("Al bijgewerkt: pyproject.toml")
    return changes


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode if path.is_file() else None
    fd, temp_name = tempfile.mkstemp(prefix=".wakesync-update-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        if mode is not None:
            os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def apply() -> int:
    changes = check_changes()
    if not changes:
        print("WakeSync 10.2.3 is al geïnstalleerd.")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = Path.home() / ".local/share/wakesync-source-backups" / (
        f"10.2.3-{stamp}-{uuid.uuid4().hex[:6]}"
    )
    backup.mkdir(parents=True, mode=0o700)
    records = []
    for name, new in changes.items():
        path = safe_path(PROJECT, name)
        exists = path.is_file()
        old = path.read_bytes() if exists else None
        if old is not None:
            saved = safe_path(backup, name)
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes(old)
        records.append({
            "path": name, "existed": exists,
            "old_sha256": checksum(old) if old is not None else None,
            "new_sha256_lf": normalized_checksum(new),
        })
    restore_manifest = backup / "manifest.json"
    restore_manifest.write_text(
        json.dumps({"project": str(PROJECT), "files": records}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    written = []
    try:
        for name, new in changes.items():
            atomic_write(safe_path(PROJECT, name), new)
            written.append(name)
    except Exception:
        # Mocht schrijven halverwege falen, keer onmiddellijk terug.
        for name in reversed(written):
            original = safe_path(backup, name)
            target = safe_path(PROJECT, name)
            if original.is_file():
                atomic_write(target, original.read_bytes())
            else:
                target.unlink(missing_ok=True)
        raise

    print("WakeSync 10.2.3 toegepast.")
    print("Herstelmanifest:", restore_manifest)
    return 0


def restore(manifest_path: Path) -> int:
    if not manifest_path.is_file():
        raise UpdateError("Herstelmanifest ontbreekt.")
    try:
        saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UpdateError("Herstelmanifest ongeldig.") from exc
    if saved.get("project") != str(PROJECT):
        raise UpdateError("Herstelmanifest hoort bij een andere repository.")
    rows = saved.get("files")
    if not isinstance(rows, list) or len(rows) != len({
        row.get("path") for row in rows if isinstance(row, dict)
    }):
        raise UpdateError("Herstelmanifest bevat dubbele of ongeldige bestanden.")

    pending = []
    for row in rows:
        name = row.get("path", "")
        if name not in EXPECTED_FILES and name != "pyproject.toml":
            raise UpdateError("Onverwacht bestand in herstelmanifest.")
        target = safe_path(PROJECT, name)
        if not target.is_file() or normalized_checksum(target.read_bytes()) != row.get("new_sha256_lf"):
            raise UpdateError(f"Herstel geweigerd; later gewijzigd: {name}")
        old = safe_path(manifest_path.parent, name)
        if row.get("existed") and (
            not old.is_file() or checksum(old.read_bytes()) != row.get("old_sha256")
        ):
            raise UpdateError(f"Back-up is ongeldig: {name}")
        pending.append((target, old if row.get("existed") else None))

    for target, old in pending:
        if old is None:
            target.unlink()
        else:
            atomic_write(target, old.read_bytes())
    print("Bronbestanden hersteld; het updatepakket is niet verwijderd.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="WakeSync 10.2.3 veilige update")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--apply", action="store_true")
    group.add_argument("--restore", metavar="MANIFEST")
    args = parser.parse_args()
    try:
        if args.restore:
            return restore(Path(args.restore).expanduser())
        if args.apply:
            return apply()
        check_changes()
        print("Compatibiliteit gecontroleerd; niets gewijzigd. Gebruik --apply.")
        return 0
    except (UpdateError, OSError, ValueError) as exc:
        print(f"Veiligheidsstop: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
