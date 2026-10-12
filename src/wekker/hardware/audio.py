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


class AplaySpeaker:
    """ALSA-speler die onmiddellijk stopt bij snooze en niets in de GUI blokkeert."""

    def __init__(self, command: str = "aplay", device: str = "") -> None:
        self.command = command
        self.device = device.strip()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._process: subprocess.Popen | None = None
        self._current: tuple[str, int] | None = None

    @property
    def is_playing(self) -> bool:
        with self._lock:
            return (self._current is not None
                    and self._worker_thread is not None
                    and self._worker_thread.is_alive()
                    and not self._stop.is_set())

    def play(self, sound: str, volume: int) -> None:
        wav_data = maak_wav(sound, volume)
        with self._lock:
            if self._current == (sound, volume) and self.is_playing:
                return
        self.stop()
        with self._lock:
            self._stop = threading.Event()
            self._current = (sound, volume)
            stopper = self._stop
            thread = threading.Thread(
                target=self._run, args=(wav_data, stopper),
                name="wakesync-alarm-audio", daemon=True,
            )
            self._worker_thread = thread
            thread.start()

    def _run(self, wav_data: bytes, stopper: threading.Event) -> None:
        try:
            while not stopper.is_set():
                command = [self.command, "-q"]
                if self.device:
                    command += ["-D", self.device]
                process = subprocess.Popen(
                    command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                with self._lock:
                    if stopper.is_set():
                        process.terminate()
                    self._process = process
                try:
                    _out, error = process.communicate(input=wav_data, timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    raise RuntimeError("ALSA-speaker reageert niet")
                finally:
                    with self._lock:
                        if self._process is process:
                            self._process = None
                if stopper.is_set():
                    break
                if process.returncode != 0:
                    # Nooit de geheime instellingen of volledige bestandsnamen loggen.
                    melding = error.decode("utf-8", "replace")[:200] if error else "onbekende fout"
                    raise RuntimeError(f"ALSA kon het alarm niet afspelen: {melding}")
                stopper.wait(0.14)
        except (OSError, RuntimeError) as exc:
            if not stopper.is_set():
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
    """Gebruik echte audio op Pi, mock elders; override met WEKKER_AUDIO."""
    mode = os.environ.get("WEKKER_AUDIO", "auto").strip().lower()
    if mode not in {"auto", "mock", "alsa"}:
        log.warning("Onbekende WEKKER_AUDIO-instelling, mock-speaker gebruikt")
        return MockSpeaker()
    if mode == "mock" or (mode == "auto" and os.environ.get("PYTEST_CURRENT_TEST")):
        # Regressietests mogen niet onverwacht de fysieke speaker laten afgaan.
        return MockSpeaker()

    found_aplay = shutil.which("aplay")
    if not found_aplay:
        log.warning("aplay ontbreekt; mock-speaker gebruikt (installeer alsa-utils)")
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

    device = os.environ.get("WEKKER_AUDIO_DEVICE", "")
    log.info("WakeSync: ALSA-speaker geactiveerd")
    return AplaySpeaker(command=found_aplay, device=device)
