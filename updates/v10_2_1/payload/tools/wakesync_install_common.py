"""Gedeelde veilige bestandsupdates; geen netwerk- of systeemcommando's."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    if path.is_symlink():
        raise ValueError(f"Symbolische link niet overschrijven: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".wakesync-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def apply_transaction(
    changes: dict[Path, tuple[bytes | None, bytes, int]], backup_root: Path,
) -> Path | None:
    """Controleer alles, bewaar originals, vervang atomair en herstel bij een fout."""
    if not changes:
        return None
    for path, (before, _after, _mode) in changes.items():
        if path.is_symlink():
            raise ValueError(f"Symbolische link niet overschrijven: {path}")
        current = path.read_bytes() if path.exists() else None
        if current != before:
            raise ValueError(f"Bestand veranderde tijdens voorbereiding: {path}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = backup_root / stamp
    backup.mkdir(parents=True, exist_ok=False, mode=0o700)
    entries = []
    for index, (path, (before, after, mode)) in enumerate(changes.items()):
        old_mode = path.stat().st_mode & 0o777 if path.exists() else None
        original = f"{index:03d}.bak"
        if before is not None:
            atomic_write(backup / original, before, 0o600)
        entries.append({
            "path": str(path.resolve()), "original": original if before is not None else None,
            "before": digest(before) if before is not None else None,
            "after": digest(after), "mode": mode, "old_mode": old_mode,
        })
    manifest = {"version": 1, "complete": False, "entries": entries}
    manifest_path = backup / "manifest.json"
    atomic_write(manifest_path, json.dumps(manifest, indent=2).encode(), 0o600)
    written = []
    try:
        for path, (before, after, mode) in changes.items():
            if (path.read_bytes() if path.exists() else None) != before:
                raise ValueError(f"Bestand is intussen aangepast: {path}")
            atomic_write(path, after, mode)
            written.append(path)
    except BaseException:
        for path in reversed(written):
            before = changes[path][0]
            entry = next(e for e in entries if e["path"] == str(path.resolve()))
            if before is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, before, entry["old_mode"])
        raise
    manifest["complete"] = True
    atomic_write(manifest_path, json.dumps(manifest, indent=2).encode(), 0o600)
    return manifest_path


def restore_transaction(manifest_path: Path) -> None:
    """Herstel uitsluitend ongewijzigde eigen updates, nooit latere gebruikerswerk."""
    manifest_path = manifest_path.resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not data.get("complete"):
        raise ValueError("Geen volledig herstelmanifest; controleer de back-up handmatig.")
    prepared = []
    for entry in data["entries"]:
        path = Path(entry["path"])
        if not path.is_absolute() or path.is_symlink():
            raise ValueError("Ongeldig herstelpad.")
        current = path.read_bytes()
        if digest(current) != entry["after"]:
            raise ValueError(f"Later gewijzigd, niet automatisch herstellen: {path}")
        original_name = entry["original"]
        if original_name is not None:
            if Path(original_name).name != original_name:
                raise ValueError("Ongeldige back-upnaam.")
            before = (manifest_path.parent / original_name).read_bytes()
            if digest(before) != entry["before"]:
                raise ValueError("Back-upcontrole mislukt.")
        else:
            before = None
        prepared.append((path, before, entry["old_mode"]))
    for path, before, mode in prepared:
        if before is None:
            path.unlink()
        else:
            atomic_write(path, before, mode)
