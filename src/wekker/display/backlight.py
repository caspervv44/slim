"""Backlight-regeling voor het Raspberry Pi-touchscreen.

De code probeert achtereenvolgens:
1. Linux sysfs (/sys/class/backlight), de echte hardware-backlight.
2. ``brightnessctl`` als dat geïnstalleerd is.
3. ``xrandr --brightness`` als softwarematige fallback onder X11.

Er wordt nooit ``sudo`` gebruikt. Als de gebruiker geen schrijfrechten heeft,
wordt dat gelogd en blijft de klok gewoon werken.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


class BacklightController:
    def __init__(self, sysfs_root: str | Path = "/sys/class/backlight") -> None:
        override = os.getenv("WEKKER_BACKLIGHT_PATH", "").strip()
        self._root = Path(override) if override else Path(sysfs_root)
        self._last_percent: int | None = None
        self._warned = False

    @staticmethod
    def _clamp(percent: int) -> int:
        return max(0, min(100, int(percent)))

    def set_percent(self, percent: int) -> bool:
        """Pas helderheid toe. Geeft True terug zodra een methode slaagt."""
        percent = self._clamp(percent)
        if self._last_percent == percent:
            return True

        methods = (self._set_sysfs, self._set_brightnessctl, self._set_xrandr)
        for method in methods:
            try:
                if method(percent):
                    self._last_percent = percent
                    self._warned = False
                    return True
            except Exception as exc:
                log.debug("backlightmethode %s faalde: %s", method.__name__, exc)

        if not self._warned:
            log.warning(
                "schermhelderheid kon niet worden toegepast; "
                "controleer /sys/class/backlight-rechten of installeer brightnessctl"
            )
            self._warned = True
        return False

    def _set_sysfs(self, percent: int) -> bool:
        if not self._root.exists():
            return False

        # Als WEKKER_BACKLIGHT_PATH direct naar één device wijst, gebruik dat.
        candidates: list[Path]
        if (self._root / "brightness").exists():
            candidates = [self._root]
        else:
            candidates = sorted(p for p in self._root.iterdir() if p.is_dir())

        for device in candidates:
            brightness = device / "brightness"
            maximum = device / "max_brightness"
            if not brightness.exists() or not maximum.exists():
                continue
            try:
                max_value = int(maximum.read_text(encoding="ascii").strip())
                if max_value <= 0:
                    continue
                raw = round(max_value * percent / 100)
                # Bij 0% is volledig uitzetten gewenst; anders minstens 1.
                if percent > 0:
                    raw = max(1, raw)
                brightness.write_text(str(raw), encoding="ascii")
                return True
            except (OSError, ValueError):
                continue
        return False

    def _set_brightnessctl(self, percent: int) -> bool:
        exe = shutil.which("brightnessctl")
        if not exe:
            return False
        result = subprocess.run(
            [exe, "-q", "set", f"{percent}%"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
            check=False,
        )
        return result.returncode == 0

    def _set_xrandr(self, percent: int) -> bool:
        exe = shutil.which("xrandr")
        if not exe or not os.getenv("DISPLAY"):
            return False
        probe = subprocess.run(
            [exe, "--current"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=4,
            check=False,
        )
        if probe.returncode != 0:
            return False

        output = ""
        for line in probe.stdout.splitlines():
            match = re.match(r"^([A-Za-z0-9_.:-]+)\s+connected(?:\s|$)", line)
            if match:
                output = match.group(1)
                break
        if not output:
            return False

        factor = max(0.10, percent / 100) if percent > 0 else 0.10
        result = subprocess.run(
            [exe, "--output", output, "--brightness", f"{factor:.2f}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
            check=False,
        )
        return result.returncode == 0
