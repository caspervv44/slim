"""Backlight-regeling voor het Raspberry Pi-touchscreen.

De code probeert achtereenvolgens:
1. Linux sysfs (/sys/class/backlight), de echte hardware-backlight.
2. ``brightnessctl`` als dat geïnstalleerd is.
3. ``ddcutil`` voor HDMI/DisplayPort-schermen met DDC/CI.
4. ``xrandr --brightness`` als softwarematige fallback onder X11.

Er wordt nooit ``sudo`` gebruikt. Als de gebruiker geen schrijfrechten heeft,
wordt dat gelogd en blijft de klok gewoon werken.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

log = logging.getLogger(__name__)


class BacklightController:
    def __init__(self, sysfs_root: str | Path = "/sys/class/backlight") -> None:
        override = os.getenv("WEKKER_BACKLIGHT_PATH", "").strip()
        self._root = Path(override) if override else Path(sysfs_root)
        self._last_percent: int | None = None
        self._warned = False
        self._worker_lock = threading.Lock()
        self._worker_running = False
        self._pending_percent: int | None = None

    @staticmethod
    def _clamp(percent: int) -> int:
        return max(0, min(100, int(percent)))

    def set_percent_async(self, percent: int) -> None:
        """Plan een helderheidswijziging zonder de GUI te blokkeren.

        Sommige HDMI-methodes (vooral DDC/CI) kunnen meerdere seconden nodig
        hebben om te melden dat een scherm de functie niet ondersteunt. De
        nieuwste gewenste waarde wordt daarom in een worker verwerkt. Als er
        tijdens die worker een nieuwe waarde binnenkomt, wordt alleen die
        nieuwste waarde daarna nog toegepast.
        """
        percent = self._clamp(percent)
        with self._worker_lock:
            self._pending_percent = percent
            if self._worker_running:
                return
            self._worker_running = True

        def worker() -> None:
            try:
                while True:
                    with self._worker_lock:
                        value = self._pending_percent
                        self._pending_percent = None
                    if value is None:
                        return
                    self.set_percent(value)
                    with self._worker_lock:
                        if self._pending_percent is None:
                            return
            finally:
                with self._worker_lock:
                    self._worker_running = False
                    # Een waarde kan precies tussen de laatste controle en het
                    # vrijgeven van de worker zijn binnengekomen.
                    pending = self._pending_percent
                if pending is not None:
                    self.set_percent_async(pending)

        threading.Thread(
            target=worker,
            name="wakesync-backlight",
            daemon=True,
        ).start()

    def set_percent(self, percent: int) -> bool:
        """Pas helderheid toe. Geeft True terug zodra een methode slaagt."""
        percent = self._clamp(percent)
        if self._last_percent == percent:
            return True

        methods = (
            self._set_sysfs,
            self._set_brightnessctl,
            self._set_ddcutil,
            self._set_xrandr,
        )
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
                "geen bruikbare backlight-driver gevonden; probeer brightnessctl of ddcutil"
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

    def _set_ddcutil(self, percent: int) -> bool:
        """Gebruik DDC/CI voor externe HDMI/DP-schermen als dat beschikbaar is.

        Dit helpt juist op systemen waar ``/sys/class/backlight`` leeg is.
        Niet elk touchscreen ondersteunt DDC/CI; falen is daarom geen fout.
        """
        exe = shutil.which("ddcutil")
        if not exe:
            return False
        result = subprocess.run(
            [exe, "--noverify", "setvcp", "10", str(percent)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=False,
        )
        return result.returncode == 0

    def _set_xrandr(self, percent: int) -> bool:
        # xrandr regelt alleen een X11-output. Onder Raspberry Pi OS/labwc
        # (Wayland) kan een XWayland-output bestaan die niet het echte HDMI-
        # scherm bestuurt; probeer die route daarom niet.
        if os.getenv("XDG_SESSION_TYPE", "").lower() == "wayland":
            return False
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
