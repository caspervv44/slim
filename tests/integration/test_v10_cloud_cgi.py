from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

PERL = shutil.which("perl")


def run_json_cgi(
    script: Path,
    data_dir: Path,
    payload: dict,
    *,
    device: str = "",
    key: str = "",
) -> tuple[str, dict]:
    body = json.dumps(payload)
    env = os.environ.copy()
    env.update(
        {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": "application/json",
            "CONTENT_LENGTH": str(len(body.encode("utf-8"))),
            "QUERY_STRING": "",
            "WEKKER_DATA_DIR": str(data_dir),
            "WEKKER_PUBLIC_URL": "https://example.test/test2.pl",
        }
    )
    if device:
        env["HTTP_X_WEKKER_DEVICE"] = device
    if key:
        env["HTTP_X_WEKKER_KEY"] = key

    result = subprocess.run(
        [PERL, str(script)],
        input=body,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    raw = result.stdout
    _, _, body_text = raw.partition("\n\n")
    if not body_text:
        _, _, body_text = raw.partition("\r\n\r\n")
    return raw, json.loads(body_text)


@pytest.mark.skipif(PERL is None, reason="Perl niet beschikbaar")
def test_v10_cloud_roundtrip_met_meerdere_alarmen_en_liquid_motion(tmp_path: Path):
    script = Path(__file__).parents[2] / "deploy" / "cloud" / "test2.pl"
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    device = "a" * 64
    key = "b" * 64
    settings = {
        "alarm": {
            "time": "06:45",
            "enabled": True,
            "snooze_minutes": 9,
            "sound": "beep",
            "volume": 70,
            "speaker_enabled": True,
            "lamp_brightness": 100,
            "lamp_blink": True,
            "blink_pattern": "blink",
            "ramp_up_seconds": 30,
            "alarms": [
                {
                    "id": "school",
                    "time": "06:45",
                    "enabled": True,
                    "snooze_minutes": 9,
                    "sound": "beep",
                    "volume": 70,
                    "speaker_enabled": True,
                    "lamp_brightness": 100,
                    "lamp_blink": True,
                    "blink_pattern": "blink",
                    "ramp_up_seconds": 30,
                },
                {
                    "id": "weekend",
                    "time": "09:10",
                    "date": "2026-10-04",
                    "enabled": False,
                    "snooze_minutes": 10,
                    "sound": "beep",
                    "volume": 55,
                    "speaker_enabled": True,
                    "lamp_brightness": 60,
                    "lamp_blink": False,
                    "blink_pattern": "steady",
                    "ramp_up_seconds": 0,
                },
            ],
        },
        "lamp": {"duration_after_button": 30, "on_with_alarm": True},
        "display": {
            "brightness": 80,
            "theme": "midnight",
            "on_duration_seconds": 30,
            "sleep_after_seconds": 60,
            "sleep_view": "logo_time_date",
            "sleep_effect": "liquid_motion",
            "sleep_glow_intensity": 82,
            "night_mode": "dim",
            "night_start": "23:00",
            "night_end": "07:00",
            "visible_fields": ["time", "next_alarm", "first_lesson", "teacher", "room"],
        },
        "agenda": {"provider": "myx", "auto_sync_minutes": 15},
        "locale": {"timezone": "Europe/Amsterdam", "region": "NL", "time_format": "24h"},
    }

    raw, registered = run_json_cgi(
        script,
        data_dir,
        {
            "action": "register",
            "device_id": device,
            "device_key": key,
            "username": "basis",
            "initial_password": "AbCdEfGh23456789",
            "settings": settings,
        },
    )
    assert "Status: 200 OK" in raw
    assert registered["ok"] is True
    assert registered["revision"] == 1

    raw, pulled = run_json_cgi(
        script, data_dir, {"action": "pull"}, device=device, key=key
    )
    assert "Status: 200 OK" in raw
    assert pulled["ok"] is True
    assert len(pulled["settings"]["alarm"]["alarms"]) == 2
    assert pulled["settings"]["alarm"]["alarms"][1]["id"] == "weekend"
    assert pulled["settings"]["alarm"]["alarms"][1]["date"] == "2026-10-04"
    assert pulled["settings"]["display"]["sleep_effect"] == "liquid_motion"


@pytest.mark.skipif(PERL is None, reason="Perl niet beschikbaar")
def test_v10_cloud_weigert_teveel_alarmprofielen(tmp_path: Path):
    script = Path(__file__).parents[2] / "deploy" / "cloud" / "test2.pl"
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    settings = {
        "alarm": {
            "alarms": [
                {"id": f"a{i}", "time": "07:30", "enabled": True}
                for i in range(13)
            ]
        }
    }
    raw, payload = run_json_cgi(
        script,
        data_dir,
        {
            "action": "register",
            "device_id": "c" * 64,
            "device_key": "d" * 64,
            "username": "basis",
            "initial_password": "AbCdEfGh23456789",
            "settings": settings,
        },
    )
    assert "Status: 400 Bad Request" in raw
    assert payload["ok"] is False


def test_v10_1_web_tabs_gebruiken_csp_nonce_en_no_js_fallback():
    script = Path(__file__).parents[2] / "deploy" / "cloud" / "test2.pl"
    source = script.read_text(encoding="utf-8")
    assert "script-src 'nonce-$nonce'" in source
    assert '<script nonce="$nonce">' in source
    assert "document.documentElement.classList.add('js')" in source
    assert ".settings-panel{display:block}" in source
    assert ".js .settings-panel{display:none}" in source
    assert "name=\"alarm_date\"" in source
