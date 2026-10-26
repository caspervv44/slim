#!/usr/bin/env python3
"""WakeSync 10.2.2: veilige bronpatch voor exact gecontroleerde bestaande code.

Gebruik in de geclonede GitHub-repository:
  py -3 tools/apply_wakesync_v1022.py --check
  py -3 tools/apply_wakesync_v1022.py --apply

Er worden nooit gebruikersinstellingen, kalibratie of opgeslagen feeds gewijzigd.
"""
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
MANIFEST = PROJECT / "updates/v10_2_2/manifest.json"
PAYLOAD = PROJECT / "updates/v10_2_2/payload"


class InstallError(RuntimeError):
    pass


def sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def lf_hash(blob: bytes) -> str:
    # Git op Windows kan CRLF uitchecken, terwijl Linux LF gebruikt.
    return sha256(blob.replace(b"\r\n", b"\n"))


def veilige_bestandsnaam(root: Path, path: str) -> Path:
    relative = Path(path)
    if relative.is_absolute() or not path or ".." in relative.parts or "\\" in path:
        raise InstallError("Ongeldige relatieve bestandsnaam in updatepakket.")
    target = root / relative
    if not target.resolve().is_relative_to(root.resolve()):
        raise InstallError("Update probeert buiten de repository te schrijven.")
    if target.is_symlink():
        raise InstallError(f"Symbolische koppeling wordt niet vervangen: {path}")
    return target


def manifest_inlezen() -> list[dict]:
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InstallError(f"Updatepakket is onvolledig: {exc}") from exc
    if data.get("release") != "10.2.2":
        raise InstallError("Verkeerde updateversie.")
    files = data.get("files")
    if not isinstance(files, list) or len(files) != 9:
        raise InstallError("Verkeerde bestandslijst in het updatepakket.")
    paths = [row.get("path") for row in files if isinstance(row, dict)]
    if len(paths) != len(files) or len(set(paths)) != len(files):
        raise InstallError("Ongeldige dubbele bestandsnaam in het updatepakket.")
    for row in files:
        if not all(isinstance(row.get(key), str)
                   for key in ("path", "base_sha256_lf", "payload_sha256")):
            raise InstallError("Update bevat ongeldige bestandsgegevens.")
        veilige_bestandsnaam(PROJECT, row["path"])
        payload_file = veilige_bestandsnaam(PAYLOAD, row["path"])
        if not payload_file.is_file():
            raise InstallError(f"Payload ontbreekt: {row['path']}")
        if sha256(payload_file.read_bytes()) != row["payload_sha256"]:
            raise InstallError(f"Payload-checksum klopt niet: {row['path']}")
    return files


def nieuwe_projectversie(content: bytes) -> bytes:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InstallError("pyproject.toml is geen UTF-8.") from exc

    section = re.search(r"(?ms)^\[project\]\s*\r?\n(.*?)(?=^\[|\Z)", text)
    if section is None:
        raise InstallError("pyproject.toml mist een [project]-sectie.")
    body = section.group(1)
    matched = list(re.finditer(r'(?m)^(\s*version\s*=\s*)(["\'])(10\.2\.1|10\.2\.2)\2', body))
    if len(matched) != 1:
        raise InstallError("Projectversie wijkt af: verwacht 10.2.1 of 10.2.2.")
    m = matched[0]
    if m.group(3) == "10.2.2":
        return content
    updated_body = body[:m.start(3)] + "10.2.2" + body[m.end(3):]
    updated = text[:section.start(1)] + updated_body + text[section.end(1):]
    return updated.encode("utf-8")


def inspecteer() -> dict[str, bytes]:
    """Alle bestanden eerst controleren; geen gedeeltelijke aanpassingen."""
    required = manifest_inlezen()
    changes: dict[str, bytes] = {}
    for row in required:
        rel = row["path"]
        target = veilige_bestandsnaam(PROJECT, rel)
        if not target.is_file():
            raise InstallError(f"Bestand ontbreekt: {rel}. Niet geforceerd.")
        current = target.read_bytes()
        new = (PAYLOAD / rel).read_bytes()
        if lf_hash(current) == lf_hash(new):
            print(f"Al bijgewerkt: {rel}")
        elif lf_hash(current) == row["base_sha256_lf"]:
            changes[rel] = new
            print(f"Wijziging: {rel}")
        else:
            raise InstallError(
                f"Veiligheidsstop: {rel} is sinds de aangeleverde broncode gewijzigd. "
                "Niets overschreven; upload dit bestand voor een gerichte samenvoeging."
            )

    project_file = PROJECT / "pyproject.toml"
    if not project_file.is_file() or project_file.is_symlink():
        raise InstallError("pyproject.toml ontbreekt of is een symlink.")
    original = project_file.read_bytes()
    updated = nieuwe_projectversie(original)
    if updated != original:
        changes["pyproject.toml"] = updated
        print("Wijziging: pyproject.toml (versie 10.2.2)")
    else:
        print("Al bijgewerkt: pyproject.toml")
    return changes


def schrijf_atomair(path: Path, content: bytes) -> None:
    """Behoud naam/permissies, maak een tijdelijke kopie en vervang pas daarna."""
    old_mode = path.stat().st_mode if path.exists() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".wakesync-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if old_mode is not None:
            os.chmod(tmp, old_mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def backup_directory() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = Path.home() / ".local/share/wakesync-source-backups" / (
        f"10.2.2-{stamp}-{uuid.uuid4().hex[:6]}"
    )
    path.mkdir(parents=True, mode=0o700)
    return path


def toepassen() -> int:
    changes = inspecteer()
    if not changes:
        print("WakeSync 10.2.2 was al toegepast. Niets gewijzigd.")
        return 0
    backup = backup_directory()
    records = []
    for rel, new in changes.items():
        path = veilige_bestandsnaam(PROJECT, rel)
        before = path.read_bytes()
        backup_file = veilige_bestandsnaam(backup, rel)
        backup_file.parent.mkdir(parents=True, exist_ok=True)
        backup_file.write_bytes(before)
        records.append({
            "path": rel,
            "old_sha256": sha256(before),
            "new_sha256_lf": lf_hash(new),
        })
    restore_manifest = backup / "manifest.json"
    restore_manifest.write_text(
        json.dumps({"project": str(PROJECT), "files": records}, indent=2) + "\n",
        encoding="utf-8",
    )

    written: list[str] = []
    try:
        for rel, new in changes.items():
            schrijf_atomair(veilige_bestandsnaam(PROJECT, rel), new)
            written.append(rel)
    except Exception:
        # Bij een schijffout exact terugzetten wat vóór de patch bestond.
        for rel in reversed(written):
            data = (backup / rel).read_bytes()
            schrijf_atomair(veilige_bestandsnaam(PROJECT, rel), data)
        raise
    print("WakeSync 10.2.2 broncode toegepast.")
    print("Back-up + herstelmanifest:", restore_manifest)
    print("Controleer nu met: py -3 -m compileall -q src/wekker")
    return 0


def herstellen(manifest_path: Path) -> int:
    if not manifest_path.is_file():
        raise InstallError("Herstelmanifest bestaat niet.")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InstallError(f"Herstelmanifest onleesbaar: {exc}") from exc
    if data.get("project") != str(PROJECT):
        raise InstallError("Dit herstelmanifest hoort bij een andere projectmap.")
    files = data.get("files")
    if not isinstance(files, list):
        raise InstallError("Herstelmanifest bevat geen bestandslijst.")
    restored = []
    for row in files:
        rel = row["path"]
        current = veilige_bestandsnaam(PROJECT, rel)
        old = veilige_bestandsnaam(manifest_path.parent, rel)
        if not old.is_file() or sha256(old.read_bytes()) != row["old_sha256"]:
            raise InstallError(f"Back-up ongeldig: {rel}")
        if not current.is_file() or lf_hash(current.read_bytes()) != row["new_sha256_lf"]:
            raise InstallError(f"Nieuwe wijzigingen gevonden in {rel}; herstel geweigerd.")
        restored.append((current, old))
    for current, old in restored:
        schrijf_atomair(current, old.read_bytes())
    print("Bronbestanden hersteld. Nieuw toegevoegde updatebestanden zijn niet verwijderd.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Veilige WakeSync 10.2.2 broncode-update")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--restore", metavar="MANIFEST")
    args = parser.parse_args()
    try:
        if args.restore:
            return herstellen(Path(args.restore).expanduser())
        if args.apply:
            return toepassen()
        changes = inspecteer()
        print("Controle geslaagd. Niets gewijzigd. Gebruik --apply.")
        return 0
    except (InstallError, OSError) as exc:
        print(f"Veiligheidsstop: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
