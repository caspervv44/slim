from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

PERL = shutil.which("perl")


def run_get(script: Path, data_dir: Path, query: str) -> str:
    env = os.environ.copy()
    env.update(
        {
            "REQUEST_METHOD": "GET",
            "QUERY_STRING": query,
            "WEKKER_DATA_DIR": str(data_dir),
            "WEKKER_PUBLIC_URL": "https://example.test/test2.pl",
        }
    )
    result = subprocess.run(
        [PERL, str(script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.skipif(PERL is None, reason="Perl niet beschikbaar")
def test_loginpagina_is_responsive_en_toont_openbare_configuratie_tabs(tmp_path: Path):
    script = Path(__file__).parents[2] / "deploy" / "cloud" / "test2.pl"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    device = "b" * 64
    record = {
        "schema_version": 10,
        "device_id": device,
        "sessions": {},
        "settings": {
            "alarm": {"time": "07:30"},
            "lamp": {"duration_after_button": 30, "on_with_alarm": True},
            "display": {"theme": "midnight"},
            "agenda": {"provider": "myx", "auto_sync_minutes": 15},
            "locale": {"timezone": "Europe/Amsterdam", "region": "NL", "time_format": "24h"},
        },
    }
    (data_dir / f"device_{device}.json").write_text(json.dumps(record), encoding="utf-8")

    output = run_get(script, data_dir, f"d={device}")
    assert "Status: 200 OK" in output
    assert "public-feature-tabs" in output
    assert ">Alarm<" in output
    assert ">Weergave<" in output
    assert ">Rooster<" in output
    assert ">Systeem<" in output
    assert "@media(max-width:760px)" in output


@pytest.mark.skipif(PERL is None, reason="Perl niet beschikbaar")
def test_health_endpoint_is_v10(tmp_path: Path):
    script = Path(__file__).parents[2] / "deploy" / "cloud" / "test2.pl"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    output = run_get(script, data_dir, "health=1")
    assert '"service":"wakesync"' in output.replace(" ", "")
    assert '"version":10' in output.replace(" ", "")
