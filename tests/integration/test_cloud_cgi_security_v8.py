from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlencode

import pytest


PERL = shutil.which("perl")


def run_cgi(script: Path, data_dir: Path, body: str) -> str:
    env = os.environ.copy()
    env.update(
        {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": "application/x-www-form-urlencoded",
            "CONTENT_LENGTH": str(len(body.encode("utf-8"))),
            "QUERY_STRING": "",
            "WEKKER_DATA_DIR": str(data_dir),
            "WEKKER_PUBLIC_URL": "https://example.test/test2.pl",
        }
    )
    result = subprocess.run(
        [PERL, str(script)],
        input=body,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.skipif(PERL is None, reason="Perl niet beschikbaar")
@pytest.mark.parametrize(
    ("action", "extra_secret"),
    [
        ("save", "23:59"),
        ("password", "SUPERGEHEIM-WACHTWOORD-123"),
    ],
)
def test_anonieme_web_post_toont_geen_instellingen_of_formulierdata(
    tmp_path: Path, action: str, extra_secret: str
) -> None:
    script = Path(__file__).parents[2] / "deploy" / "cloud" / "test2.pl"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    device = "a" * 64

    # Voor de A3-gate is alleen een bestaand record met géén sessie nodig.
    record = {
        "device_id": device,
        "sessions": {},
        "settings": {
            "alarm": {"time": "06:42"},
            "display": {"theme": "midnight"},
            "locale": {"timezone": "Europe/Amsterdam"},
        },
    }
    (data_dir / f"device_{device}.json").write_text(
        json.dumps(record), encoding="utf-8"
    )

    form = {"action": action, "d": device, "csrf": "vals-token"}
    if action == "save":
        form["alarm_time"] = extra_secret
    else:
        form["new_password"] = extra_secret
        form["confirm_password"] = extra_secret

    output = run_cgi(script, data_dir, urlencode(form))
    assert "Status: 401 Unauthorized" in output
    assert extra_secret not in output
    assert "06:42" not in output
    assert "Log in" in output or "Inloggen" in output
