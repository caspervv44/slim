#!/usr/bin/env python3
"""Korte, vrijwillige hardwaretest van het speakertje op de Raspberry Pi."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from wekker.hardware.audio import AplaySpeaker, make_speaker


def main() -> None:
    parser=argparse.ArgumentParser(description="Korte ALSA-luidsprekertest")
    parser.add_argument("--seconds",type=float,default=2.0)
    parser.add_argument("--volume",type=int,default=40)
    parser.add_argument("--sound",choices=["beep","classic","soft","digital"],default="soft")
    args=parser.parse_args()
    if not 0.4 <= args.seconds <= 5:
        parser.error("--seconds moet tussen 0.4 en 5 liggen")
    if not 0 <= args.volume <= 100:
        parser.error("--volume moet tussen 0 en 100 liggen")

    os.environ["WEKKER_AUDIO"]="alsa"
    speaker=make_speaker()
    if not isinstance(speaker,AplaySpeaker):
        raise SystemExit("Geen ALSA-uitgang: installeer alsa-utils en controleer aplay -l")
    try:
        print(f"Start: {args.seconds:g} seconde(n) · volume {args.volume}%")
        speaker.play(args.sound,args.volume)
        time.sleep(args.seconds)
    finally:
        speaker.stop()
    print("Test afgelopen. Hoorde je niets? Controleer aplay -l / ALSA-device.")


if __name__=="__main__":
    main()
