"""Echte (optionele) Raspberry Pi-speaker via ALSA, zonder Python-dependencies.

De GUI/alarmkern gebruikt het bestaande Speaker-protocol. Op andere systemen
blijven MockSpeaker en alle bestaande tests ongewijzigd werken. De ALSA-driver
speelt korte WAV-klanken doorlopend tot snooze of stoppen; de GUI blokkeert niet.
"""
from __future__ import annotations

import io
import logging
import math
import os
import re
from pathlib import Path
import shutil
import struct
import subprocess
import threading
import wave

from wekker.hardware.mock import MockSpeaker

log = logging.getLogger(__name__)
SAMPLE_RATE = 22050


def maak_wav(sound: str, volume: int) -> bytes:
    """Genereer één korte alarmfrase als 16-bit PCM WAV, zonder externe bestanden."""
    if not isinstance(sound, str) or not sound.strip():
        raise ValueError("Geluid mag niet leeg zijn")
    if not isinstance(volume, int) or isinstance(volume, bool) or not 0 <= volume <= 100:
        raise ValueError("Volume moet een getal tussen 0 en 100 zijn")

    # De vier vertrouwde geluiden blijven exact gelijk. Extra melodieën zijn
    # synthetisch en gebruiken dezelfde werkende ALSA/USB-audioketen.
    from wekker.hardware.tone_patterns import maak_melodie_wav
    from wekker.alarm.sounds import ALARM_SOUND_IDS
    if sound in ALARM_SOUND_IDS and sound not in {"beep", "classic", "soft", "digital"}:
        return maak_melodie_wav(sound, volume)

    presets = {
        "beep": (740.0, 0.24, 0.10),
        "classic": (660.0, 0.18, 0.11),
        "soft": (520.0, 0.36, 0.16),
        "digital": (880.0, 0.14, 0.08),
    }
    frequency, duration, silence = presets.get(sound.lower(), presets["beep"])
    tones = 3
    total_samples = round(SAMPLE_RATE * (duration + silence) * tones)
    gain = 0.40 * (volume / 100) ** 1.6
    pcm = bytearray()
    for index in range(total_samples):
        offset = index / SAMPLE_RATE
        cycle_position = offset % (duration + silence)
        if cycle_position >= duration:
            value = 0.0
        else:
            # Korte fade-in/out voorkomt onaangename klikjes in de speaker.
            fade = min(1.0, cycle_position / 0.012, (duration - cycle_position) / 0.020)
            pitch = frequency
            if sound.lower() == "digital":
                pitch += 100 if int(offset / (duration + silence)) % 2 else 0
            value = gain * max(0.0, fade) * math.sin(2 * math.pi * pitch * offset)
        pcm.extend(struct.pack("<h", int(32767 * value)))
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(bytes(pcm))
    return stream.getvalue()


def kies_audioapparaten(command: str) -> tuple[str, ...]:
    """Kies eerst de desktopspeaker en vervolgens een aanwezige USB-geluidskaart.

    De omgevingsvariabele WEKKER_AUDIO_DEVICE heeft altijd voorrang. Met
    'plughw' converteert ALSA ons WAV-formaat ook voor eenvoudige USB-kaarten.
    Een herkend USB-apparaat krijgt NOOIT stilzwijgend HDMI als fallback.
    """
    gekozen = os.environ.get("WEKKER_AUDIO_DEVICE", "").strip()
    if gekozen:
        return (gekozen,)
    # Eventuele persoonlijke, lokaal ingestelde audiokeuze overleeft een reboot,
    # zonder een wijziging aan de startscriptjes of de Windows-GitHub-repository.
    config_path = Path.home() / ".config" / "wakesync" / "audio-device.txt"
    try:
        opgeslagen = config_path.read_text(encoding="utf-8").strip()
    except OSError:
        opgeslagen = ""
    if opgeslagen:
        if len(opgeslagen) <= 120 and re.fullmatch(r"[A-Za-z0-9_,.:=+/-]+", opgeslagen):
            return (opgeslagen,)
        log.warning("Ongeldige lokale audio-uitgang genegeerd")

    kandidaten: list[str] = []
    # YouTube gebruikt vaak PipeWire/PulseAudio. Als de actieve sessie er een
    # ALSA-ingang voor aanbiedt, gaat het alarm naar dezelfde uitvoer.
    runtime_dir = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{getattr(os, 'getuid', lambda: 0)()}")
    pulse_socket = runtime_dir / "pulse" / "native"
    pipewire_socket = runtime_dir / "pipewire-0"
    if pulse_socket.is_socket() or pipewire_socket.is_socket():
        try:
            result = subprocess.run(
                [command, "-L"], capture_output=True, text=True,
                timeout=3, check=False,
            )
            # Alleen exacte, beschikbare PCM-namen gebruiken.
            pcm_names = {
                line.strip() for line in result.stdout.splitlines()
                if line and not line[0].isspace()
            }
            if pulse_socket.is_socket() and "pulse" in pcm_names:
                kandidaten.append("pulse")
            if pipewire_socket.is_socket() and "pipewire" in pcm_names:
                kandidaten.append("pipewire")
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("ALSA-uitgangen opvragen mislukt: %s", exc)

    try:
        # Het ALSA-kaart-ID is stabieler dan 'card 2', dat na een reboot kan schuiven.
        cards = Path("/proc/asound/cards").read_text(encoding="utf-8")
    except OSError:
        cards = ""
    usb_ids = re.findall(
        r"(?im)^\s*\d+\s+\[([A-Za-z0-9_-]+)\s*\]\s*:\s*USB-Audio\b",
        cards,
    )
    for card_id in usb_ids:
        route = f"plughw:CARD={card_id},DEV=0"
        if route not in kandidaten:
            kandidaten.append(route)

    return tuple(kandidaten) if kandidaten else ("",)


class AplaySpeaker:
    """ALSA-audio op een workerthread met direct stoppen en zichtbare foutstatus."""

    def __init__(
        self, command: str = "aplay", device: str = "",
        fallback_devices: tuple[str, ...] = (),
    ) -> None:
        self.command = command
        self.device = device.strip()
        self._devices = tuple(dict.fromkeys((self.device, *fallback_devices)))
        self._active_device: str | None = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._process: subprocess.Popen | None = None
        self._current: tuple[str, int] | None = None
        self._last_error: str | None = None

    @property
    def is_playing(self) -> bool:
        with self._lock:
            return (self._current is not None
                    and self._worker_thread is not None
                    and self._worker_thread.is_alive()
                    and not self._stop.is_set())

    @property
    def last_error(self) -> str | None:
        """Laat een eventuele fout ook aan de testknop en diagnosetool zien."""
        with self._lock:
            return self._last_error

    @property
    def active_device(self) -> str:
        with self._lock:
            return self._active_device if self._active_device is not None else self.device

    def play(self, sound: str, volume: int) -> None:
        wav_data = maak_wav(sound, volume)
        with self._lock:
            if self._current == (sound, volume) and self.is_playing:
                return
        self.stop()
        with self._lock:
            self._stop = threading.Event()
            self._current = (sound, volume)
            self._last_error = None
            stopper = self._stop
            thread = threading.Thread(
                target=self._run, args=(wav_data, stopper),
                name="wakesync-alarm-audio", daemon=True,
            )
            self._worker_thread = thread
            thread.start()

    def _speel_frase(self, wav_data: bytes, stopper: threading.Event) -> bool:
        errors: list[str] = []
        with self._lock:
            prefer = self._active_device
        routes = list(dict.fromkeys(
            ([prefer] if prefer is not None else []) + list(self._devices)
        ))
        for route in routes:
            if stopper.is_set():
                return False
            command = [self.command, "-q"]
            if route:
                command += ["-D", route]
            try:
                process = subprocess.Popen(
                    command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
            except OSError as exc:
                errors.append(f"{route or 'default'}: {exc}")
                continue
            with self._lock:
                self._process = process
                if stopper.is_set():
                    process.terminate()
            try:
                _out, error = process.communicate(input=wav_data, timeout=8)
                code = process.returncode
                melding = error.decode("utf-8", "replace").strip()[:150] if error else ""
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                code = -1
                melding = "audio-uitgang reageert niet"
            finally:
                with self._lock:
                    if self._process is process:
                        self._process = None
            if stopper.is_set():
                return False
            if code == 0:
                with self._lock:
                    self._active_device = route
                return True
            errors.append(f"{route or 'default'}: {melding or 'afspelen mislukt'}")
        if not stopper.is_set():
            raise RuntimeError(" / ".join(errors)[:350] or "Geen werkende audio-uitgang")
        return False

    def _run(self, wav_data: bytes, stopper: threading.Event) -> None:
        try:
            while not stopper.is_set():
                if not self._speel_frase(wav_data, stopper):
                    break
                stopper.wait(0.14)
        except (OSError, RuntimeError) as exc:
            if not stopper.is_set():
                with self._lock:
                    self._last_error = str(exc)
                log.error("WakeSync-geluid gestopt: %s", exc)
        finally:
            with self._lock:
                if self._stop is stopper:
                    self._current = None
                    self._process = None

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            process = self._process
            self._current = None
            self._process = None
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            except OSError as exc:
                log.warning("ALSA-proces stoppen: %s", exc)


def make_speaker():
    """Maak op de Pi een echte speaker; mocks alleen bij tests/uitdrukkelijke keuze."""
    mode = os.environ.get("WEKKER_AUDIO", "auto").strip().lower()
    if mode not in {"auto", "mock", "alsa"}:
        log.warning("Onbekende WEKKER_AUDIO-instelling, mock-speaker gebruikt")
        return MockSpeaker()
    if mode == "mock" or (mode == "auto" and os.environ.get("PYTEST_CURRENT_TEST")):
        return MockSpeaker()

    found_aplay = shutil.which("aplay")
    if not found_aplay:
        log.error("aplay ontbreekt: WakeSync heeft geen echte geluidsuitgang!")
        return MockSpeaker()

    if mode == "auto":
        try:
            model = Path("/proc/device-tree/model").read_bytes().decode(
                "utf-8", "replace",
            ).rstrip("\0")
        except OSError:
            model = ""
        if "Raspberry Pi" not in model:
            return MockSpeaker()

    routes = kies_audioapparaten(found_aplay)
    log.info("WakeSync-audio: ALSA-route(s) %s", ", ".join(route or "default" for route in routes))
    return AplaySpeaker(
        command=found_aplay, device=routes[0], fallback_devices=routes[1:],
    )
