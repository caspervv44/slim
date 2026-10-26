"""Veilige drie-weg-samenvoeging voor gewijzigde WakeSync-bronbestanden."""
from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import apply_wakesync_v1021 as updater

BASE = ROOT / "updates/v10_2_1/bases"
PAYLOAD = ROOT / "updates/v10_2_1/payload"


def reference(name: str):
    base = (BASE / name).read_bytes()
    updated = (PAYLOAD / name).read_bytes()
    return base, updated, {updater.text_hash(base)}


@unittest.skipUnless(shutil.which("git"), "Git is vereist om veilig samen te voegen")
class MergeCompatibilityTests(unittest.TestCase):
    def test_exact_base_gets_updated(self):
        for name in sorted(updater.MERGEABLE):
            before, updated, hashes = reference(name)
            with self.subTest(file=name):
                merged = updater.merge_premium_source(name, before, updated, hashes)
                self.assertEqual(updater.normalized(merged), updater.normalized(updated))

    def test_customizations_elsewhere_are_preserved(self):
        for name in sorted(updater.MERGEABLE):
            before, updated, hashes = reference(name)
            if name.endswith("/premium.py"):
                anchor = b"        mapping = {\n"
                addition = b"        # Deze GitHub-commentaarregel moet blijven.\n"
            else:
                anchor = b'    return image.convert("RGB").resize((WIDTH,HEIGHT),Image.Resampling.LANCZOS)\n'
                addition = b"    # Mijn eigen rendering-commentaar.\n"
            with self.subTest(file=name):
                self.assertIn(anchor,before)
                changed=before.replace(anchor,addition+anchor,1)
                merged=updater.merge_premium_source(name,changed,updated,hashes)
                self.assertIn(addition,merged)
                self.assertNotEqual(updater.text_hash(merged),updater.text_hash(updated))
                self.assertEqual(merged,updater.merge_premium_source(name,merged,updated,hashes))

    def test_overlapping_changes_raise_without_writing(self):
        name="src/wekker/gui/premium_render.py"
        before,updated,hashes=reference(name)
        anchor=b"self.card(216,14,566,54,radius=14,alpha=240)"
        self.assertIn(anchor,before)
        changed=before.replace(anchor,b"self.card(216,12,566,54,radius=14,alpha=240)",1)
        with self.assertRaisesRegex(ValueError,"overlappen"):
            updater.merge_premium_source(name,changed,updated,hashes)

    def test_windows_line_endings_preserved(self):
        name="src/wekker/gui/premium.py"
        before,updated,hashes=reference(name)
        changed=before.replace(b"        mapping = {\n",b"        # Behoud CRLF.\n        mapping = {\n",1)
        changed=changed.replace(b"\n",b"\r\n")
        merged=updater.merge_premium_source(name,changed,updated,hashes)
        self.assertIn(b"        # Behoud CRLF.\r\n",merged)
        self.assertNotIn(b"\n",merged.replace(b"\r\n",b""))

    def test_rejects_untrusted_reference(self):
        name="src/wekker/gui/premium.py"
        before,updated,_=reference(name)
        with self.assertRaisesRegex(ValueError,"niet vertrouwd"):
            updater.merge_premium_source(name,before,updated,{"not-expected"})


if __name__ == "__main__":
    unittest.main()
