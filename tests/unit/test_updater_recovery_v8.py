from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from wekker.updater import _WORKER_SCRIPT


@pytest.mark.parametrize(
    "phase",
    ["backup", "stage", "journal", "remove", "copy", "pip", "health", "restart"],
)
def test_update_worker_herstelt_oude_code_bij_iedere_fase(tmp_path: Path, phase: str) -> None:
    project = tmp_path / "project"
    source = tmp_path / "new"
    project.mkdir()
    source.mkdir()

    (project / "src").mkdir()
    (project / "src" / "marker.txt").write_text("OUD", encoding="utf-8")
    (project / "README.md").write_text("oude readme", encoding="utf-8")
    (project / "pyproject.toml").write_text(
        '[project]\nname="wekker"\nversion="7.0.0"\n', encoding="utf-8"
    )
    local_data = project / "wekker-settings.json"
    local_data.write_text('{"geheim":"blijft"}', encoding="utf-8")

    (source / "src").mkdir()
    (source / "src" / "marker.txt").write_text("NIEUW", encoding="utf-8")
    (source / "README.md").write_text("nieuwe readme", encoding="utf-8")
    (source / "pyproject.toml").write_text(
        '[project]\nname="wekker"\nversion="8.0.0"\n', encoding="utf-8"
    )

    fake_python = tmp_path / "fake-python"
    fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_python.chmod(0o755)

    worker = tmp_path / "worker.py"
    worker.write_text(_WORKER_SCRIPT, encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "project_root": str(project),
                "new_root": str(source),
                "python": str(fake_python),
                "restart_args": [str(fake_python)],
                "parent_pid": 99999999,
                "target_version": "8.0.0",
                "settings_path": "wekker-settings.json",
                "_test_fail_phase": phase,
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(worker), str(config)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
    )
    assert result.returncode != 0

    assert (project / "src" / "marker.txt").read_text(encoding="utf-8") == "OUD"
    assert (project / "README.md").read_text(encoding="utf-8") == "oude readme"
    assert 'version="7.0.0"' in (project / "pyproject.toml").read_text(encoding="utf-8")
    assert local_data.read_text(encoding="utf-8") == '{"geheim":"blijft"}'

    status = json.loads((project / ".wakesync-update-status.json").read_text(encoding="utf-8"))
    assert status["status"] == "rolled_back"
