"""Regressie: behoud de GitHub-constructorfix bij de WakeSync 10.2.1-update.

Deze test bouwt een tijdelijke kloon uit de exacte 10.2.0-basis.
Hij schrijft nooit in de echte WakeSync-repository.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import apply_wakesync_v1021 as updater
from wakesync_install_common import apply_transaction, restore_transaction

ORIGINAL_SUPER = b"        super().__init__(root, runtime, navigator)\n"
GITHUB_SUPER = b"""        try:
            super().__init__(root, runtime, navigator)
        except TypeError:
            # Val terug op 2-arg basis (bv. StubApp in test_gui_kiosk die
            # via monkeypatch als basis wordt gebonden bij lazy import).
            super().__init__(root, runtime)  # type: ignore[misc]
"""
EXPECTED_GITHUB_HASH = "179649c25b3862565a45785de84d53d02a98eb7072b5a91c47997a2b0a8fdbee"


def make_fixture(root: Path) -> tuple[Path, bytes]:
    repo = root / "repository"
    gui = repo / "src/wekker/gui"
    gui.mkdir(parents=True)
    (repo / "src/wekker/__init__.py").write_text('__version__ = "10.2.0"\n')
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "wekker"\nversion = "10.2.0"\n'
        '[project.scripts]\nwekker = "wekker.main:main"\n'
    )
    (gui / "app.py").write_text(
        'class TouchApp:\n'
        '    def _show_update_overlay(self): pass\n'
        '    def _show_settings_section(self, section):\n'
        '        if section == "diagnostics": pass\n'
        '    # De premium-interface wordt door PremiumTouchApp opgebouwd.\n'
    )
    base = (ROOT / "updates/v10_2_1/bases/src/wekker/gui/premium.py").read_bytes()
    assert base.count(ORIGINAL_SUPER) == 1
    github = base.replace(ORIGINAL_SUPER, GITHUB_SUPER)
    assert updater.text_hash(github) == EXPECTED_GITHUB_HASH
    # De Windows-kloon bevat CRLF; hashes moeten dit herkennen.
    (gui / "premium.py").write_bytes(github.replace(b"\n", b"\r\n"))
    renderer = (ROOT / "updates/v10_2_1/bases/src/wekker/gui/premium_render.py").read_bytes()
    (gui / "premium_render.py").write_bytes(renderer.replace(b"\n", b"\r\n"))
    return repo, github


class ExactGitHubMerge(unittest.TestCase):
    def test_uploaded_premium_version_accepted_and_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, original = make_fixture(Path(tmp))
            changes = updater.build_plan(repo)
            before = (repo / "src/wekker/gui/premium.py").read_bytes()
            self.assertEqual(updater.normalized(before), original)
            premium = next(path for path in changes if path.name == "premium.py")
            updated = changes[premium][1]
            self.assertIn(GITHUB_SUPER, updater.normalized(updated))
            self.assertIn(b"self._root.after(700, self._premium_poll_focus)", updated)
            self.assertIn(b"self._premium_open_system_page(payload)", updated)
            self.assertIn(b"\"settings\",\"settings\",\"software\"", changes[next(
                path for path in changes if path.name == "premium_render.py"
            )][1])
            self.assertEqual(updater.build_plan(repo), changes)  # Alleen lezen.
            self.assertEqual(before, (repo / "src/wekker/gui/premium.py").read_bytes())

    def test_apply_is_idempotent_and_restore_recovers_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _ = make_fixture(Path(tmp))
            before = (repo / "src/wekker/gui/premium.py").read_bytes()
            plan = updater.build_plan(repo)
            manifest = apply_transaction(plan, Path(tmp) / "backups")
            self.assertEqual(updater.build_plan(repo), {})
            self.assertIn(
                b"except TypeError:",
                (repo / "src/wekker/gui/premium.py").read_bytes(),
            )
            restore_transaction(manifest)
            self.assertEqual(
                (repo / "src/wekker/gui/premium.py").read_bytes(), before
            )
            self.assertEqual(
                (repo / "src/wekker/__init__.py").read_text().strip(),
                '__version__ = "10.2.0"',
            )

    def test_unknown_conflicting_source_still_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _ = make_fixture(Path(tmp))
            premium = repo / "src/wekker/gui/premium.py"
            text = premium.read_bytes()
            # Zelfde constructorvlak, maar ander gedrag: nooit forceren.
            premium.write_bytes(text.replace(
                b"super().__init__(root, runtime)  # type: ignore[misc]",
                b"super().__init__(root, special_runtime)",
            ))
            with self.assertRaisesRegex(ValueError, "overlappen"):
                updater.build_plan(repo)
            self.assertNotIn(b"_premium_poll_focus", premium.read_bytes())


if __name__ == "__main__":
    unittest.main()
