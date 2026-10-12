"""Veiligheidsproeven voor het activeren en verwijderen van de GUI-patch."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


def _load(filename: str, module_name: str):
    import sys
    sys.path.insert(0,str(TOOLS))
    spec = importlib.util.spec_from_file_location(module_name,TOOLS/filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sandbox(tmp_path: Path) -> Path:
    repo=tmp_path/"repo"
    (repo/"src/wekker/gui").mkdir(parents=True)
    (repo/"src/wekker/assets").mkdir(parents=True)
    (repo/"src/wekker/__init__.py").write_text('__version__ = "10.1.1"\n')
    (repo/"src/wekker/gui/app.py").write_text(
        "def launch_gui(runtime):\n"
        "    app = TouchApp(root, runtime)\n"
        "    app.tick()\n"
    )
    (repo/"src/wekker/gui/premium.py").write_text("# Premium GUI\n")
    (repo/"src/wekker/assets/premium_midnight.png").write_bytes(b"image")
    (repo/"src/wekker/assets/wakesync-logo.png").write_bytes(b"existing-brand")
    return repo


def test_activeren_werkt_eenmaal_en_is_omkeerbaar(tmp_path,monkeypatch):
    apply=_load("apply_premium.py","install_premium_test")
    remove=_load("remove_premium.py","uninstall_premium_test")
    repo=_sandbox(tmp_path)
    app=repo/"src/wekker/gui/app.py"
    backup=tmp_path/"app.py.original"
    monkeypatch.setattr(apply,"_root",lambda:repo)
    monkeypatch.setattr(apply,"_backup_path",lambda r:backup)
    monkeypatch.setattr(remove,"_root",lambda:repo)
    monkeypatch.setattr(remove,"_backup_path",lambda r:backup)
    assert apply.activate()==0
    assert "PremiumTouchApp(root, runtime)" in app.read_text()
    assert apply.activate()==0
    assert backup.exists()
    assert remove.restore()==0
    assert "app = TouchApp(root, runtime)" in app.read_text()


def test_onbekende_versie_wordt_niet_overschreven(tmp_path,monkeypatch):
    apply=_load("apply_premium.py","install_premium_version_test")
    repo=_sandbox(tmp_path)
    (repo/"src/wekker/__init__.py").write_text('__version__ = "11.0.0"\n')
    monkeypatch.setattr(apply,"_root",lambda:repo)
    before=(repo/"src/wekker/gui/app.py").read_bytes()
    assert apply.activate()==2
    assert (repo/"src/wekker/gui/app.py").read_bytes()==before


def test_missende_haak_wijzigingen_wordt_niet_overschreven(tmp_path,monkeypatch):
    apply=_load("apply_premium.py","install_premium_other_test")
    repo=_sandbox(tmp_path)
    app=repo/"src/wekker/gui/app.py"
    app.write_text("andere code")
    monkeypatch.setattr(apply,"_root",lambda:repo)
    assert apply.activate()==2
    assert app.read_text()=="andere code"
