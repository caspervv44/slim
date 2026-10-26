"""WakeSync 10.2.2: touchscreen-stop, USB-audio en lampvrije bediening."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import io
import os
import re
import threading
import time
from types import SimpleNamespace as NS
import wave

import pytest

from wekker.alarm.core import AlarmClock
from wekker.alarm.state import AlarmState
from wekker.clock import FakeClock
from wekker.hardware.mock import MockSpeaker, MockLamp
from wekker.settings import default_settings
from wekker.gui.app import TouchApp
from wekker.gui.premium_render import render_screen, render_detail_screen, PALETTES
from wekker.hardware import audio
from wekker.api.server import INDEX_HTML

ASSETS = Path(__file__).resolve().parents[1] / "src" / "wekker" / "assets"
NOW = datetime.fromisoformat("2026-10-28T06:59:00+01:00")


def create_alarm():
    settings = default_settings()
    settings.alarm.enabled = True
    settings.alarm.speaker_enabled = True
    clock = FakeClock(NOW)
    speaker = MockSpeaker()
    lamp = MockLamp()
    return AlarmClock(settings, clock, speaker, lamp), clock, speaker


def test_aanraakstop_terwijl_alarm_klinkt():
    core, _clock, speaker = create_alarm()
    assert core.trigger()
    assert core.state == AlarmState.RINGING
    assert core.dismiss(touchscreen=True) is True
    assert core.state == AlarmState.DISMISSED
    assert not speaker.is_playing
    assert core.snooze() is False
    assert core.dismiss(touchscreen=True) is False


def test_aanraakstop_ook_tijdens_snooze():
    core, clock, speaker = create_alarm()
    assert core.trigger()
    assert core.snooze()
    assert core.state == AlarmState.SNOOZED
    assert not speaker.is_playing
    assert core.dismiss(touchscreen=True)
    clock.advance(timedelta(minutes=20))
    assert core.tick() == AlarmState.DISMISSED
    assert not speaker.is_playing


def test_bestaande_onbevestigde_api_kan_niet_stil_stoppen():
    core, clock, speaker = create_alarm()
    assert core.trigger()
    assert not core.dismiss(physical=False)
    assert core.state == AlarmState.RINGING
    assert speaker.is_playing
    assert core.dismiss(physical=True) is True


def test_touch_handler_stopt_echte_core_en_sluit_overlay():
    core, _clock, _speaker = create_alarm()
    assert core.trigger()
    app = TouchApp.__new__(TouchApp)
    app._runtime = NS(ctx=NS(core=core))
    events: list[str] = []
    app._ensure_alarm_overlay = lambda: events.append("overlay-bijwerken")
    app._show_toast = lambda message, error=False: events.append(message)
    app._dismiss_alarm_from_screen()
    assert core.state == AlarmState.DISMISSED
    assert events == ["overlay-bijwerken", "Alarm gestopt"]


@pytest.mark.parametrize("theme", list(PALETTES))
def test_premium_lijst_heeft_speaker_maar_geen_lamp(theme):
    layout = {"screen": "alarm", "time": "07:00", "items": [
        {"id": "alarm-1", "time": "07:00", "enabled": True,
         "snooze_minutes": 9, "speaker_enabled": True, "lamp_blink": True},
    ]}
    image, hits = render_screen(layout, theme, NOW, ASSETS)
    assert image.size == (800, 480)
    actions = {hit.action for hit in hits}
    assert {"toggle-speaker", "toggle-alarm", "cycle-snooze"} <= actions
    assert "toggle-lamp" not in actions
    # Grote geluidszone, naast de bestaande alarm-aan/uitknop.
    sound = next(h for h in hits if h.action == "toggle-speaker")
    assert sound.x1 - sound.x0 >= 90


@pytest.mark.parametrize("theme", list(PALETTES))
def test_premium_details_geen_lampknoppen(theme):
    data = {"id": "alarm-1", "time": "07:00", "enabled": True,
            "snooze_minutes": 9, "speaker_enabled": True,
            "sound": "beep", "volume": 70, "ramp_up_seconds": 30,
            "lamp_blink": True, "lamp_brightness": 100, "blink_pattern": "pulse"}
    image, hits = render_detail_screen("alarm", theme, NOW, ASSETS, item=data)
    assert image.size == (800, 480)
    actions = {h.action for h in hits}
    assert {"alarm-snooze", "alarm-sound", "alarm-speaker", "alarm-volume",
            "alarm-ramp", "test-audio"} <= actions
    assert not ({"alarm-lamp", "alarm-lamp-brightness", "alarm-pattern"} & actions)


def test_cloud_beheerscherm_verwijst_niet_naar_virtuele_lamp():
    assert 'id="st_lamp"' not in INDEX_HTML
    assert 'id="f_lamp"' not in INDEX_HTML
    assert 'id="f_lampdur"' not in INDEX_HTML
    assert "Lamp testen" not in INDEX_HTML
    assert "Geluid testen" in INDEX_HTML
    assert "alarm:{time:" in INDEX_HTML


@pytest.fixture
def audio_setup(monkeypatch, tmp_path):
    monkeypatch.delenv("WEKKER_AUDIO_DEVICE", raising=False)
    monkeypatch.setattr(audio.Path, "home", classmethod(lambda cls: tmp_path))
    cards = " 0 [vc4hdmi0      ]: vc4-hdmi - HDMI\n 2 [Device         ]: USB-Audio - USB Audio Device\n"
    original_read = audio.Path.read_text

    def mock_read(path, *args, **kwargs):
        if str(path) == "/proc/asound/cards":
            return cards
        if str(path).endswith("audio-device.txt"):
            raise FileNotFoundError(str(path))
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(audio.Path, "read_text", mock_read)
    monkeypatch.setattr(audio.Path, "is_socket", lambda path: False)


def test_usb_automatisch_niet_hdmi(audio_setup):
    assert audio.kies_audioapparaten("/usr/bin/aplay") == ("plughw:CARD=Device,DEV=0",)


def test_explicit_audio_device_overrides_usb(audio_setup, monkeypatch):
    monkeypatch.setenv("WEKKER_AUDIO_DEVICE", "plughw:CARD=TEST,DEV=1")
    assert audio.kies_audioapparaten("/usr/bin/aplay") == ("plughw:CARD=TEST,DEV=1",)


def test_local_audio_device_override(monkeypatch, tmp_path):
    monkeypatch.delenv("WEKKER_AUDIO_DEVICE", raising=False)
    p = tmp_path / ".config/wakesync/audio-device.txt"
    p.parent.mkdir(parents=True)
    p.write_text("plughw:CARD=Device,DEV=0\n")
    monkeypatch.setattr(audio.Path, "home", classmethod(lambda cls: tmp_path))
    assert audio.kies_audioapparaten("/usr/bin/aplay") == ("plughw:CARD=Device,DEV=0",)


def test_pulse_en_usb_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("WEKKER_AUDIO_DEVICE", raising=False)
    monkeypatch.setattr(audio.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(audio.Path, "is_socket",
                        lambda p: str(p).endswith("/pulse/native"))
    def fake_read(path, *a, **kw):
        if str(path) == "/proc/asound/cards":
            return " 2 [Device      ]: USB-Audio - USB Audio Device\n"
        raise FileNotFoundError

    monkeypatch.setattr(audio.Path, "read_text", fake_read)
    monkeypatch.setattr(audio.subprocess, "run",
                        lambda *a, **kw: NS(stdout="pulse\n    server\n"))
    assert audio.kies_audioapparaten("aplay") == (
        "pulse", "plughw:CARD=Device,DEV=0",
    )


def test_audio_fallback_na_pulse_fout(monkeypatch):
    commands = []

    class P:
        def __init__(self, cmd, **_kw):
            commands.append(cmd)
            self.returncode = None
        def communicate(self, input, timeout):
            self.returncode = 1 if "pulse" in commands[-1] else 0
            return b"", (b"pulse not available" if self.returncode else b"")
        def poll(self):
            return self.returncode

    monkeypatch.setattr(audio.subprocess, "Popen", P)
    speaker = audio.AplaySpeaker(command="aplay", device="pulse",
                                fallback_devices=("plughw:CARD=Device,DEV=0",))
    assert speaker._speel_frase(b"fake WAV", threading.Event()) is True
    assert speaker.active_device == "plughw:CARD=Device,DEV=0"
    assert len(commands) == 2


def test_audiofout_wordt_bewaard_en_is_zichtbaar(monkeypatch):
    class P:
        def __init__(self, cmd, **_kw):
            self.returncode = 1
        def communicate(self, input, timeout):
            return b"", b"device not found"
        def poll(self):
            return self.returncode
    monkeypatch.setattr(audio.subprocess, "Popen", P)
    speaker = audio.AplaySpeaker(command="aplay", device="plughw:CARD=Device,DEV=0")
    speaker.play("beep", 65)
    for _ in range(50):
        if speaker.last_error:
            break
        time.sleep(.01)
    assert "device not found" in (speaker.last_error or "")
    assert speaker.is_playing is False
    speaker.stop()


def test_alarm_wav_is_geldig():
    data = audio.maak_wav("beep", 65)
    with wave.open(io.BytesIO(data)) as stream:
        assert stream.getframerate() == 22050
        assert stream.getnchannels() == 1
        assert stream.getsampwidth() == 2
        assert stream.getnframes() > 20000


def test_ui_bevat_fysieke_knop_niet_meer():
    import inspect
    from wekker.gui.app import TouchApp
    source = inspect.getsource(TouchApp._ensure_alarm_overlay)
    assert "gebruik de fysieke knop" not in source
    assert "Alarm stoppen" in source
    assert "_overlay_alarm_stop" in source
