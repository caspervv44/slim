"""JSON-opslag voor instellingen. Atomair schrijven, geschikt voor Pi (SD-kaart)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class JsonStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, Any] | None:
        """Geef het opgeslagen dict terug, of None als er geen bestand is."""
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise StorageError(f"Kan instellingen niet lezen uit {self.path}: {exc}") from exc

    def save(self, data: dict[str, Any]) -> None:
        """Schrijf atomair (tmp-bestand + replace) zodat stroomuitval minder schaadt."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=str(self.path.parent), prefix=self.path.name + ".", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2, ensure_ascii=False)
                    fh.write("\n")
                    # Naar schijf dwingen vóór de atomische replace, zodat een
                    # stroomstoring op de Pi geen leeg/half bestand achterlaat.
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, self.path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except OSError as exc:
            raise StorageError(f"Kan instellingen niet schrijven naar {self.path}: {exc}") from exc


class StorageError(Exception):
    """Opslagfout (lezen/schrijven)."""
