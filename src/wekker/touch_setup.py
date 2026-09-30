"""Veilige touchscreen-/beeldconfiguratie voor ondersteunde WakeSync-hardware.

V8 ondersteunt één bevestigd profiel:
``waveshare-5-hdmi-ads7846`` — 5-inch 800×480 HDMI-display met ADS7846
resistive touch op Raspberry Pi OS Bookworm/labwc.

De helper is idempotent, maakt back-ups vóór wijzigingen en schrijft alleen
een gemarkeerd blok in bootconfig. Bestaande instellingen buiten dat blok
blijven ongemoeid. Op een reeds werkende kernel-driver wordt bootconfig niet
onnodig gewijzigd; dan corrigeert WakeSync alleen de labwc-outputmapping.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from typing import Callable

from wekker.storage import JsonStore

PROFILE_ID = "waveshare-5-hdmi-ads7846"
PROFILE_LABEL = "Waveshare 5-inch HDMI 800×480 + ADS7846"
TOUCH_NAME = "ADS7846 Touchscreen"
DEFAULT_OUTPUT = "HDMI-A-1"

BOOT_BEGIN = "# BEGIN WAKESYNC WAVESHARE5 ADS7846"
BOOT_END = "# END WAKESYNC WAVESHARE5 ADS7846"
BOOT_BLOCK = """# BEGIN WAKESYNC WAVESHARE5 ADS7846
# WakeSync v8: profiel voor het bekende 5-inch Waveshare HDMI/ADS7846-scherm.
dtparam=spi=on
dtoverlay=ads7846,cs=1,penirq=25,penirq_pull=2,speed=50000,keep_vref_on=0,swapxy=0,pmax=255,xohms=60
# Forceer alleen de bekende 800x480 HDMI-modus voor dit profiel.
hdmi_force_hotplug=1
hdmi_group=2
hdmi_mode=87
hdmi_cvt=800 480 60 6 0 0 0
# END WAKESYNC WAVESHARE5 ADS7846
"""


@dataclass(frozen=True)
class TouchStatus:
    profile: str
    profile_label: str
    detected_touch: bool
    output: str
    output_800x480: bool
    mapping_ok: bool
    configured: bool
    restart_required: bool
    needs_profile_confirmation: bool
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


class TouchSetupError(RuntimeError):
    pass


class TouchConfigurator:
    def __init__(
        self,
        *,
        home: str | Path | None = None,
        boot_config: str | Path | None = None,
        input_devices: str | Path = "/proc/bus/input/devices",
        state_path: str | Path | None = None,
        command_runner: Callable[..., subprocess.CompletedProcess] | None = None,
    ) -> None:
        self.home = Path(home or Path.home())
        self.input_devices = Path(input_devices)
        self.boot_config = Path(boot_config) if boot_config else self._find_boot_config()
        self.labwc_path = self.home / ".config" / "labwc" / "rc.xml"
        self.labwc_system_path = Path("/etc/xdg/labwc/rc.xml")
        self.state_path = Path(
            state_path or (self.home / ".config" / "wakesync" / "touch-state.json")
        )
        self._runner = command_runner or subprocess.run

    def detect(self) -> TouchStatus:
        touch = self._touch_detected()
        output, is_800 = self._detect_output()
        mapping_ok = self._mapping_matches(output or DEFAULT_OUTPUT)
        state = self._load_state()
        restart_required = bool(state.get("restart_required"))
        configured = touch and is_800 and mapping_ok
        if configured:
            message = "Touchscreen en HDMI-output zijn correct gekoppeld."
        elif touch and is_800 and not mapping_ok:
            message = (
                f"{TOUCH_NAME} is gevonden, maar labwc is nog niet gekoppeld aan "
                f"{output or DEFAULT_OUTPUT}."
            )
        elif touch:
            message = "Touchdriver gevonden; 800×480-output kon niet worden bevestigd."
        else:
            message = (
                "ADS7846 is niet gedetecteerd. Kies het Waveshare-profiel alleen "
                "als dit exact het aangesloten scherm is."
            )
        return TouchStatus(
            profile=PROFILE_ID,
            profile_label=PROFILE_LABEL,
            detected_touch=touch,
            output=output or DEFAULT_OUTPUT,
            output_800x480=is_800,
            mapping_ok=mapping_ok,
            configured=configured,
            restart_required=restart_required,
            needs_profile_confirmation=not touch,
            message=message,
        )

    def apply(
        self,
        *,
        profile: str = PROFILE_ID,
        confirmed: bool = False,
    ) -> TouchStatus:
        if profile != PROFILE_ID:
            raise TouchSetupError(f"onbekend hardwareprofiel: {profile}")
        before = self.detect()
        if before.needs_profile_confirmation and not confirmed:
            raise TouchSetupError(
                "hardwareprofiel moet expliciet worden bevestigd omdat ADS7846 "
                "nog niet door de kernel wordt gedetecteerd"
            )

        output = before.output or DEFAULT_OUTPUT
        changed = False
        mapping_changed = self._ensure_labwc_mapping(output)
        changed |= mapping_changed
        if mapping_changed:
            self._reconfigure_labwc()

        # Als de driver al door de kernel is geladen, raak bootconfig niet aan.
        # Op een schone installatie voegt het bevestigde profiel het driver- en
        # displayblok toe. Hiervoor zijn normaal rootrechten nodig.
        if not before.detected_touch:
            changed |= self._ensure_boot_profile()

        state = {
            "schema_version": 1,
            "profile": PROFILE_ID,
            "output": output,
            "applied_at": _iso_now(),
            "restart_required": bool(changed and not before.detected_touch),
            "pending_verification": bool(changed),
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        JsonStore(self.state_path).save(state)

        after = self.detect()
        # Zonder bootwijziging kan mapping direct goed zijn. Bij driverwijziging
        # is de status pas na een reboot definitief.
        return TouchStatus(
            **{
                **after.to_dict(),
                "restart_required": bool(state["restart_required"]),
                "configured": (
                    after.configured if not state["restart_required"] else False
                ),
                "message": (
                    "Configuratie opgeslagen; herstart Raspberry Pi OS om de "
                    "ADS7846-driver te laden. WakeSync controleert daarna automatisch."
                    if state["restart_required"]
                    else after.message
                ),
            }
        )

    def verify_after_boot(self) -> TouchStatus:
        status = self.detect()
        state = self._load_state()
        if status.configured and state:
            state["restart_required"] = False
            state["pending_verification"] = False
            state["verified_at"] = _iso_now()
            JsonStore(self.state_path).save(state)
            return TouchStatus(
                **{
                    **status.to_dict(),
                    "restart_required": False,
                    "message": "Touchscreencontrole na herstart geslaagd.",
                }
            )
        return status

    def auto_fix_mapping_if_known(self) -> TouchStatus:
        """Corrigeer alleen de veilige gebruikersmapping bij bekende hardware.

        Geen sudo en geen bootconfig. Dit kan bij iedere appstart idempotent.
        """
        status = self.detect()
        if status.detected_touch and status.output_800x480 and not status.mapping_ok:
            if self._ensure_labwc_mapping(status.output):
                self._reconfigure_labwc()
            return self.detect()
        return status

    # -- detectie --------------------------------------------------------
    def _touch_detected(self) -> bool:
        try:
            return TOUCH_NAME in self.input_devices.read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            return False

    def _detect_output(self) -> tuple[str, bool]:
        # Wayland/labwc: wlr-randr is de bron van waarheid voor mapToOutput.
        try:
            result = self._runner(
                ["wlr-randr"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3,
                check=False,
            )
            text = result.stdout or ""
            current = ""
            enabled = False
            has_800 = False
            for raw in text.splitlines():
                if raw and not raw.startswith((" ", "\t")):
                    if current and enabled:
                        return current, has_800
                    current = raw.split()[0]
                    enabled = False
                    has_800 = False
                stripped = raw.strip().lower()
                if stripped.startswith("enabled:") and "yes" in stripped:
                    enabled = True
                if "800x480" in stripped:
                    has_800 = True
            if current and enabled:
                return current, has_800
        except Exception:
            pass

        # Fallback op DRM-sysfs. Namen card1-HDMI-A-1 -> HDMI-A-1.
        drm = Path("/sys/class/drm")
        try:
            for entry in sorted(drm.iterdir()):
                status_file = entry / "status"
                if not status_file.exists():
                    continue
                try:
                    connected = status_file.read_text().strip() == "connected"
                except OSError:
                    continue
                if not connected:
                    continue
                match = re.search(r"(HDMI-A-\d+)$", entry.name)
                if match:
                    modes = ""
                    try:
                        modes = (entry / "modes").read_text()
                    except OSError:
                        pass
                    return match.group(1), "800x480" in modes
        except OSError:
            pass
        return DEFAULT_OUTPUT, False

    # -- labwc -----------------------------------------------------------
    def _ensure_labwc_mapping(self, output: str) -> bool:
        self.labwc_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.labwc_path.exists():
            if self.labwc_system_path.exists():
                shutil.copy2(self.labwc_system_path, self.labwc_path)
            else:
                self.labwc_path.write_text(
                    "<openbox_config></openbox_config>\n", encoding="utf-8"
                )

        original = self.labwc_path.read_text(encoding="utf-8", errors="replace")
        try:
            root = ET.fromstring(original)
        except ET.ParseError as exc:
            raise TouchSetupError(f"labwc rc.xml is ongeldig: {exc}") from exc

        changed = False
        matches = []
        for touch in list(root.findall(".//touch")):
            name = touch.get("deviceName")
            if name is None:
                child = touch.find("deviceName")
                name = child.text.strip() if child is not None and child.text else ""
            if name == TOUCH_NAME:
                matches.append(touch)

        if matches:
            primary = matches[0]
            # Maak de door labwc ondersteunde attribute-vorm eenduidig.
            desired = {
                "deviceName": TOUCH_NAME,
                "mapToOutput": output,
                "mouseEmulation": "yes",
            }
            if primary.attrib != desired or list(primary):
                primary.attrib.clear()
                primary.attrib.update(desired)
                for child in list(primary):
                    primary.remove(child)
                changed = True
            # Dubbele entries verwijderen.
            for duplicate in matches[1:]:
                parent = _find_parent(root, duplicate)
                if parent is not None:
                    parent.remove(duplicate)
                    changed = True
        else:
            ET.SubElement(
                root,
                "touch",
                {
                    "deviceName": TOUCH_NAME,
                    "mapToOutput": output,
                    "mouseEmulation": "yes",
                },
            )
            changed = True

        if not changed:
            return False
        self._backup(self.labwc_path)
        _indent_xml(root)
        ET.ElementTree(root).write(
            self.labwc_path, encoding="unicode", xml_declaration=False
        )
        with self.labwc_path.open("a", encoding="utf-8") as handle:
            handle.write("\n")
        return True

    def _mapping_matches(self, output: str) -> bool:
        if not self.labwc_path.exists():
            return False
        try:
            root = ET.fromstring(self.labwc_path.read_text(encoding="utf-8"))
        except (OSError, ET.ParseError):
            return False
        for touch in root.findall(".//touch"):
            name = touch.get("deviceName")
            if name is None:
                child = touch.find("deviceName")
                name = child.text.strip() if child is not None and child.text else ""
            mapped = touch.get("mapToOutput")
            if mapped is None:
                child = touch.find("mapToOutput")
                mapped = child.text.strip() if child is not None and child.text else ""
            if name == TOUCH_NAME and mapped == output:
                return True
        return False

    def _reconfigure_labwc(self) -> None:
        """Vraag labwc de gebruikersconfig opnieuw in te lezen.

        Een mislukte live-reconfigure is niet fataal: de mapping staat al
        persistent in ``rc.xml`` en wordt uiterlijk bij de volgende sessie/
        reboot ingelezen.
        """
        try:
            self._runner(
                ["labwc", "--reconfigure"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3,
                check=False,
            )
        except Exception:
            pass

    # -- boot ------------------------------------------------------------
    def _find_boot_config(self) -> Path:
        for candidate in (
            Path("/boot/firmware/config.txt"),
            Path("/boot/config.txt"),
        ):
            if candidate.exists():
                return candidate
        return Path("/boot/firmware/config.txt")

    def _ensure_boot_profile(self) -> bool:
        if not self.boot_config.exists():
            raise TouchSetupError(f"bootconfig niet gevonden: {self.boot_config}")
        if not os.access(self.boot_config, os.W_OK):
            raise TouchSetupError(
                f"geen schrijfrechten op {self.boot_config}; voer touch-setup met sudo uit"
            )
        text = self.boot_config.read_text(encoding="utf-8", errors="replace")
        if BOOT_BEGIN in text and BOOT_END in text:
            # Vervang alleen ons eigen blok zodat een toekomstige profielwijziging
            # idempotent blijft.
            pattern = re.compile(
                re.escape(BOOT_BEGIN) + r".*?" + re.escape(BOOT_END) + r"\n?",
                re.DOTALL,
            )
            new_text = pattern.sub(BOOT_BLOCK, text)
        else:
            suffix = "" if text.endswith("\n") else "\n"
            new_text = text + suffix + "\n" + BOOT_BLOCK
        if new_text == text:
            return False
        self._backup(self.boot_config)
        self.boot_config.write_text(new_text, encoding="utf-8")
        return True

    def _backup(self, path: Path) -> None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = path.with_name(f"{path.name}.wakesync-backup-{stamp}")
        if not target.exists():
            shutil.copy2(path, target)

    def _load_state(self) -> dict:
        try:
            return JsonStore(self.state_path).load() or {}
        except Exception:
            return {}


def _find_parent(root: ET.Element, child: ET.Element) -> ET.Element | None:
    for parent in root.iter():
        if child in list(parent):
            return parent
    return None


def _indent_xml(elem: ET.Element, level: int = 0) -> None:
    indent = "\n" + "  " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + "  "
        for child in elem:
            _indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indent
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = indent


def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
