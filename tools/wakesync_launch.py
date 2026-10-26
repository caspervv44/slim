#!/usr/bin/env python3
"""Gebruik altijd de broncode van deze projectmap, ongeacht de huidige map."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from wekker.desktop import main

if __name__ == "__main__":
    raise SystemExit(main())
