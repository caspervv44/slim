"""Geen echte luidspreker nodig om de audio-driver te controleren."""
from __future__ import annotations

import io
import wave
import os
import pytest

# Dit ZIP is een patch bovenop GitHub, geen zelfstandig clone.
# Bij geïsoleerde pakkettests ontbreekt de bestaande mock.py nog.
import sys
import types

try:
    from wekker.hardware.mock import MockSpeaker
except ModuleNotFoundError:
    mock_module = types.ModuleType("wekker.hardware.mock")
    class MockSpeaker:
        def play(self, sound, volume): pass
        def stop(self): pass
        @property
        def is_playing(self): return False
    mock_module.MockSpeaker = MockSpeaker
    sys.modules["wekker.hardware.mock"] = mock_module

from wekker.hardware import audio


@pytest.mark.parametrize("sound", ["beep", "soft", "classic", "digital", "andere"])
@pytest.mark.parametrize("volume", [0, 30, 70, 100])
def test_geluidsframes(sound,volume):
    binary=audio.maak_wav(sound,volume)
    with wave.open(io.BytesIO(binary),"rb") as wav:
        assert wav.getnchannels()==1
        assert wav.getframerate()==22050
        assert wav.getsampwidth()==2
        assert wav.getnframes()>22050//2


def test_volume_validatie():
    for invalid in [-1,101,True,"80"]:
        with pytest.raises(ValueError):
            audio.maak_wav("beep",invalid)
    with pytest.raises(ValueError):
        audio.maak_wav("",50)


def test_default_op_pc_is_mock(monkeypatch):
    monkeypatch.setenv("WEKKER_AUDIO","auto")
    monkeypatch.setattr(audio.shutil,"which",lambda x:"/bin/aplay")
    monkeypatch.setattr(audio.Path,"read_bytes",lambda path: b"Generic PC")
    assert isinstance(audio.make_speaker(),MockSpeaker)


def test_alsa_forceren(monkeypatch):
    monkeypatch.setenv("WEKKER_AUDIO","alsa")
    monkeypatch.setattr(audio.shutil,"which",lambda x:"/bin/aplay")
    result=audio.make_speaker()
    assert isinstance(result,audio.AplaySpeaker)
    assert not result.is_playing


def test_afwezig_aplay_geeft_veilige_mock(monkeypatch):
    monkeypatch.setenv("WEKKER_AUDIO","auto")
    monkeypatch.setattr(audio.shutil,"which",lambda x:None)
    assert isinstance(audio.make_speaker(),MockSpeaker)

