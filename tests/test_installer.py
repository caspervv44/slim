"""Controleer veilige installatie, idempotentie en herstel van de agenda-hotfix."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("wakesync_hotfix_installer",ROOT/"tools/apply_agenda_hotfix.py")
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


@pytest.fixture()
def demo_repo(tmp_path):
    repo = tmp_path / "slim"
    (repo/"src/wekker/gui").mkdir(parents=True)
    (repo/"src/wekker/gui/app.py").write_text(
        "from typing import Any\n\nclass TouchApp:\n"
        "    def _data(self):\n        pass\n"
        "    def _shift_agenda_day(self, days):\n        pass\n"
        "    def _agenda_today(self):\n        pass\n\n"
        "def launch_gui(runtime: Any, fullscreen: bool = True) -> None:\n"
        "    pass\n",
        encoding="utf-8",
    )
    shutil.copy2(ROOT/"src/wekker/gui/agenda_fix.py",repo/"src/wekker/gui/agenda_fix.py")
    return repo


def test_installeren_verandert_alleen_app_py_en_herstelt(demo_repo,tmp_path):
    app_path = demo_repo/"src/wekker/gui/app.py"
    before=app_path.read_bytes()
    cache_path=demo_repo/".wakesync-agenda-cache.json"
    cache_path.write_bytes(b'{"fictieve-cache":true}')
    backup=tmp_path/"back"
    assert TOOL.apply(demo_repo, backup)==0
    after=app_path.read_text()
    assert TOOL.BEGIN in after
    ast.parse(after)
    assert cache_path.read_bytes()==b'{"fictieve-cache":true}'
    assert TOOL.apply(demo_repo, backup)==0
    assert TOOL.undo(demo_repo, backup)==0
    assert app_path.read_bytes()==before


def test_herstellen_weigert_veranderde_app(demo_repo,tmp_path):
    backup=tmp_path/"back"
    assert TOOL.apply(demo_repo,backup)==0
    p=demo_repo/"src/wekker/gui/app.py"
    p.write_text(p.read_text()+"\n# lokale wijziging\n")
    assert TOOL.undo(demo_repo,backup)==2


def test_onbekende_gui_niet_overschrijven(demo_repo,tmp_path):
    p=demo_repo/"src/wekker/gui/app.py"
    p.write_text("print('andere GUI')\n")
    old=p.read_bytes()
    assert TOOL.apply(demo_repo,tmp_path/"back")==2
    assert p.read_bytes()==old


def test_ontbrekende_module_niet_overschrijven(demo_repo,tmp_path):
    p=demo_repo/"src/wekker/gui/app.py"
    old=p.read_bytes()
    (demo_repo/"src/wekker/gui/agenda_fix.py").unlink()
    assert TOOL.apply(demo_repo,tmp_path/"back")==2
    assert p.read_bytes()==old
