"""Test de veilige, kleine source-patch zonder gebruikersbestanden te raken."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def load_installer():
    spec=importlib.util.spec_from_file_location(
        "apply_v102_testing", ROOT/"tools/apply_premium_v102.py",
    )
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def repo_fixture(tmp_path, premium_already=True):
    root=tmp_path/"repo"
    paths=[
        "src/wekker/gui/premium.py", "src/wekker/gui/premium_render.py",
        "src/wekker/hardware/audio.py",
        "src/wekker/assets/premium_midnight.png",
        "src/wekker/assets/premium_ocean.png",
        "src/wekker/assets/premium_light.png",
        "src/wekker/assets/premium_amber.png",
        "src/wekker/assets/wakesync-logo.png",
    ]
    for name in paths:
        target=root/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(b"placeholder")
    app=root/"src/wekker/gui/app.py"
    app.parent.mkdir(parents=True,exist_ok=True)
    app.write_text(
        "def launch_gui(root, runtime):\n"
        + (
            "    # [WakeSync Premium] BEGIN\n"
            "    from wekker.gui.premium import PremiumTouchApp\n"
            "    app = PremiumTouchApp(root, runtime)\n"
            "    # [WakeSync Premium] EINDE\n"
            if premium_already else
            "    app = TouchApp(root, runtime)\n"
        )
    )
    (root/"src/wekker/main.py").write_text(
        "from wekker.hardware.mock import MockButton, MockDisplay, MockLamp, MockSpeaker\n"
        "\ndef build_default():\n"
        "    speaker, lamp = MockSpeaker(), MockLamp()\n"
    )
    (root/"src/wekker/__init__.py").write_text('__version__ = "10.1.1"\n')
    (root/"pyproject.toml").write_text('[project]\nversion = "10.1.1"\n')
    return root


def test_v102_upgrade_en_revert(tmp_path):
    pkg=load_installer()
    root=repo_fixture(tmp_path)
    backup=tmp_path/"backup"
    assert pkg.apply(root,backup)==0
    main=(root/"src/wekker/main.py").read_text()
    assert "speaker, lamp = make_speaker(), MockLamp()" in main
    assert "from wekker.hardware.audio import make_speaker" in main
    assert "__version__ = \"10.2.0\"" in (root/"src/wekker/__init__.py").read_text()
    assert (backup/"manifest.json").exists()
    assert pkg.apply(root,backup)==0
    assert pkg.revert(root,backup)==0
    assert "speaker, lamp = MockSpeaker(), MockLamp()" in (root/"src/wekker/main.py").read_text()


def test_v102_upgrade_kan_oudere_premium_activeren(tmp_path):
    pkg=load_installer()
    root=repo_fixture(tmp_path,premium_already=False)
    assert pkg.apply(root,tmp_path/"backup")==0
    assert pkg.MARKER_CODE in (root/"src/wekker/gui/app.py").read_text()


def test_v102_veiligheidsstop_verkeerde_versie(tmp_path):
    pkg=load_installer()
    root=repo_fixture(tmp_path)
    (root/"src/wekker/__init__.py").write_text('__version__ = "99.0.0"\n')
    original=(root/"src/wekker/main.py").read_bytes()
    assert pkg.apply(root,tmp_path/"backup")==2
    assert original==(root/"src/wekker/main.py").read_bytes()


def test_v102_revert_overschrijft_geen_nieuwe_wijzigingen(tmp_path):
    pkg=load_installer()
    root=repo_fixture(tmp_path)
    backup=tmp_path/"backup"
    assert pkg.apply(root,backup)==0
    main=root/"src/wekker/main.py"
    main.write_text(main.read_text()+"# later handmatig veranderd\n")
    assert pkg.revert(root,backup)==2
    assert "later handmatig veranderd" in main.read_text()

