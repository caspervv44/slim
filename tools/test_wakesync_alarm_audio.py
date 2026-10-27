#!/usr/bin/env python3
"""Korte, veilige audiotest voor de echte WakeSync-alarmdriver."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from wekker.hardware.audio import AplaySpeaker, make_speaker
from wekker.alarm.sounds import ALARM_SOUND_IDS


def main() -> int:
    parser = argparse.ArgumentParser(description="Test de WakeSync-alarmuitgang op de Pi")
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--volume", type=int, default=65)
    parser.add_argument("--sound", choices=ALARM_SOUND_IDS, default="beep")
    parser.add_argument(
        "--device", default=None,
        help="Optioneel ALSA-apparaat, bijvoorbeeld plughw:CARD=Device,DEV=0",
    )
    args = parser.parse_args()

    if not 0.5 <= args.seconds <= 8:
        parser.error("--seconds moet tussen 0,5 en 8 liggen")
    if not 1 <= args.volume <= 100:
        parser.error("--volume moet tussen 1 en 100 liggen")
    if args.device is not None:
        if not args.device.strip():
            parser.error("--device mag niet leeg zijn")
        os.environ["WEKKER_AUDIO_DEVICE"] = args.device

    # Deze uitdrukkelijke hardwaretest gebruikt nooit de mock, ook niet via SSH.
    os.environ["WEKKER_AUDIO"] = "alsa"
    speaker = make_speaker()
    if not isinstance(speaker, AplaySpeaker):
        print("FOUT: geen echte ALSA-speaker. Controleer 'command -v aplay'.")
        return 2

    print("Geprobeerde uitgang(en):", ", ".join(x or "default" for x in speaker._devices), flush=True)
    print(f"Test {args.seconds:g} seconden op {args.volume}% – gebruik een prettig volume.", flush=True)
    try:
        speaker.play(args.sound, args.volume)
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            if speaker.last_error:
                print(f"FOUT: {speaker.last_error}", flush=True)
                return 2
            if not speaker.is_playing:
                print("FOUT: audio is onverwacht gestopt.", flush=True)
                return 2
            time.sleep(min(0.1, deadline - time.monotonic()))
        if speaker.last_error:
            print(f"FOUT: {speaker.last_error}", flush=True)
            return 2
        print("Actieve uitgang:", speaker.active_device or "default")
        print("De driver speelde de WAV-test af. Controleer zelf of je hem hoorde.")
        return 0
    finally:
        speaker.stop()


if __name__ == "__main__":
    raise SystemExit(main())
