"""Regressietests: 15 unieke geluiden, onafhankelijke alarmen en touchkeuze."""
from __future__ import annotations

import hashlib
import io
import struct
import types
import wave
from pathlib import Path

import pytest

from wekker.alarm.sounds import ALARM_SOUNDS, ALARM_SOUND_IDS, sound_label
from wekker.hardware.audio import maak_wav
from wekker.hardware.tone_patterns import maak_melodie_wav
from wekker.settings import AlarmSettings, Settings
from wekker.gui.premium_render import HitTarget, render_sound_picker


def test_15_unieke_sleutels_en_labels():
    assert len(ALARM_SOUNDS) == len(ALARM_SOUND_IDS) == 15
    assert len(set(ALARM_SOUND_IDS)) == 15
    assert len(set(s.label for s in ALARM_SOUNDS)) == 15
    assert ALARM_SOUND_IDS[:4] == ("beep", "classic", "soft", "digital")
    assert sound_label("marimba") == "Marimba"


@pytest.mark.parametrize("preset", ALARM_SOUNDS, ids=lambda s: s.key)
def test_alle_alarmgeluiden_zijn_echt_uniek_en_geldig(preset):
    data = maak_wav(preset.key, 65)
    with wave.open(io.BytesIO(data), "rb") as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 22050)
        assert .5 <= wav.getnframes() / wav.getframerate() <= 3.5
        pcm = wav.readframes(wav.getnframes())
    samples = [sample[0] for sample in struct.iter_unpack("<h", pcm)]
    assert max(abs(value) for value in samples) > 1000
    assert max(abs(value) for value in samples) < 32767


def test_alle_15_pcm_klanken_zijn_verschillend():
    pcm_hashes = set()
    for preset in ALARM_SOUNDS:
        pcm_hashes.add(hashlib.sha256(maak_wav(preset.key, 70)[44:]).hexdigest())
    assert len(pcm_hashes) == 15


@pytest.mark.parametrize("preset", ALARM_SOUND_IDS[4:])
def test_nieuwe_klanken_respecteren_volume_nul(preset):
    data = maak_melodie_wav(preset, 0)
    with wave.open(io.BytesIO(data), "rb") as wav:
        assert not any(wav.readframes(wav.getnframes()))


def test_oude_alarminstellingen_behouden_hun_geluid():
    legacy = Settings.from_dict({"alarm": {"time": "06:35", "sound": "classic"}})
    assert legacy.alarm.alarms[0].sound == "classic"
    assert legacy.to_dict()["alarm"]["sound"] == "classic"


def test_verschillende_klanken_per_alarm_worden_opgeslagen():
    cfg = Settings.from_dict({"alarm": {"alarms": [
        {"id": "vroeg", "time": "06:20", "sound": "sunrise"},
        {"id": "laat", "time": "07:45", "sound": "arcade"},
    ]}})
    assert cfg.alarm.get("vroeg").sound == "sunrise"
    assert cfg.alarm.get("laat").sound == "arcade"
    # Verander alleen het tweede alarm via het bestaande instellingensysteem.
    profiles = cfg.to_dict()["alarm"]["alarms"]
    profiles[1]["sound"] = "marimba"
    updated = cfg.update_from_dict({"alarm": {"alarms": profiles}})
    reloaded = Settings.from_dict(updated.to_dict())
    assert reloaded.alarm.get("vroeg").sound == "sunrise"
    assert reloaded.alarm.get("laat").sound == "marimba"
    assert reloaded.alarm.sound == "sunrise"


@pytest.mark.parametrize("theme", ("midnight", "ocean", "light", "amber"))
def test_touchkiezer_heeft_selecteer_en_luistervlak_per_geluid(theme, tmp_path):
    image, hits = render_sound_picker(theme, tmp_path, "sunrise")
    assert image.size == (800, 480)
    select = [h for h in hits if h.action == "sound-select"]
    preview = [h for h in hits if h.action == "sound-preview"]
    assert [h.payload for h in select] == list(ALARM_SOUND_IDS)
    assert [h.payload for h in preview] == list(ALARM_SOUND_IDS)
    assert [h.action for h in hits].count("close-detail") == 1
    for a in select:
        assert a.x0 >= 0 and a.y0 >= 0 and a.x1 <= 800 and a.y1 <= 480
        assert a.x1 - a.x0 >= 150 and a.y1 - a.y0 >= 60
    for b in preview:
        assert b.x1 - b.x0 >= 50 and b.y1 - b.y0 >= 60
    for first in select + preview:
        assert all(
            first.x1 <= second.x0 or second.x1 <= first.x0
            or first.y1 <= second.y0 or second.y1 <= first.y0
            for second in select + preview if second is not first
        )


def test_premium_kiezer_verwerkt_luisteren_en_alleen_geselecteerd_geluid():
    from wekker.gui.premium import PremiumTouchApp

    app = object.__new__(PremiumTouchApp)
    app._premium_detail_kind = "sound"
    app._alarm_selected_id = "alarm-2"
    app._premium_detail_hits = [HitTarget(0, 0, 180, 60, "sound-preview", "marimba"),
                                HitTarget(200, 0, 380, 60, "sound-select", "marimba")]
    calls = []
    app._preview_alarm_sound = lambda alarm_id, sound: calls.append(("listen", alarm_id, sound))
    app._save_alarm_profile_patch = lambda alarm_id, patch, **kw: calls.append(("save", alarm_id, patch)) or True
    app._premium_redraw_detail = lambda: calls.append(("redraw",))
    app._show_toast = lambda *a, **k: None
    event = lambda x: types.SimpleNamespace(x=x, y=20)
    app._premium_detail_click(event(25))
    assert calls == [("listen", "alarm-2", "marimba")]
    app._premium_detail_click(event(240))
    assert ("save", "alarm-2", {"sound": "marimba"}) in calls
    app._premium_detail_hits = [HitTarget(200, 0, 380, 60, "sound-select", "invalid")]
    before = list(calls)
    app._premium_detail_click(event(240))
    assert calls == before


def test_voorbeeld_kan_echte_wekker_niet_stilzetten():
    from wekker.gui.app import TouchApp

    class Speaker:
        def __init__(self):
            self.calls = []
            self.last_error = None
        def play(self, sound, volume):
            self.calls.append(("play", sound, volume))
        def stop(self):
            self.calls.append(("stop",))

    speaker = Speaker()
    core = types.SimpleNamespace(state=types.SimpleNamespace(value="sleeping"))
    callbacks = []
    app = object.__new__(TouchApp)
    app._runtime = types.SimpleNamespace(
        ctx=types.SimpleNamespace(core=core), speaker=speaker)
    app._root = types.SimpleNamespace(after=lambda delay, fn: callbacks.append(fn))
    app._sound_preview_token = 0
    app._alarm_item = lambda _id: {"volume": 65}
    app._show_toast = lambda *a, **k: None

    app._preview_alarm_sound("alarm-a", "sunrise")
    app._preview_alarm_sound("alarm-a", "marimba")
    assert speaker.calls == [("play", "sunrise", 65), ("play", "marimba", 65)]
    callbacks[0]()  # Een oude timer mag de tweede proef niet stoppen.
    assert not any(call[0] == "stop" for call in speaker.calls)
    core.state.value = "ringing"
    callbacks[1]()  # Een echt alarm wordt nooit door de voorbeeldtimer gestopt.
    assert not any(call[0] == "stop" for call in speaker.calls)


def test_alarmkern_gebruikt_het_geluid_van_het_actieve_profiel():
    from datetime import datetime
    from wekker.alarm.core import AlarmClock
    from wekker.hardware.mock import MockSpeaker, MockLamp

    settings = Settings.from_dict({"alarm": {"alarms": [
        {"id": "school", "time": "06:45", "sound": "sunrise", "volume": 45},
        {"id": "weekend", "time": "09:30", "sound": "arcade", "volume": 80},
    ]}})
    speaker = MockSpeaker()
    clock = types.SimpleNamespace(now=lambda: datetime(2026, 10, 27, 6, 40))
    alarm = AlarmClock(settings, clock, speaker, MockLamp())
    alarm._active_alarm_id = "school"
    alarm.sound_start()
    assert (speaker.current_sound, speaker.current_volume) == ("sunrise", 45)
    alarm._active_alarm_id = "weekend"
    alarm.sound_start()
    assert (speaker.current_sound, speaker.current_volume) == ("arcade", 80)
