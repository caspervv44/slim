"""Synthetische alarmmelodieën in standaard PCM/WAV (zonder externe assets).

Iedere preset heeft een eigen ritme en klankkleur. De maximale amplitude is
bewust begrensd; ook bij 100% blijven de samples binnen 16-bit PCM.
"""
from __future__ import annotations

import io
import math
import struct
import wave

SAMPLE_RATE = 22_050

# Elke noot: (frequentie in Hz, lengte in seconden, stilte na de noot).
# De namen zijn de opgeslagen sleutels van AlarmProfile.sound.
_MELODIES: dict[str, tuple[str, tuple[tuple[float, float, float], ...]]] = {
    "sunrise": ("warm", ((392, .24, .06), (523, .27, .06), (659, .27, .06),
                         (784, .52, .18), (659, .28, .05), (784, .43, .16))),
    "chime": ("bell", ((784, .30, .06), (659, .30, .06), (523, .34, .12),
                       (659, .31, .06), (784, .51, .15))),
    "piano": ("piano", ((262, .39, .04), (330, .39, .04), (392, .39, .04),
                       (523, .58, .14))),
    "marimba": ("marimba", ((784, .21, .045), (659, .21, .045),
                            (523, .21, .045), (392, .34, .08),
                            (523, .24, .08), (659, .28, .16))),
    "bells": ("bell", ((392, .49, .08), (523, .48, .08),
                       (659, .51, .08), (523, .69, .18))),
    "radar": ("radar", ((880, .12, .24), (880, .12, .24), (988, .12, .24),
                        (880, .12, .26))),
    "pulse": ("pulse", ((440, .13, .09), (440, .21, .31),
                        (523, .13, .09), (523, .21, .33),
                        (440, .13, .09), (440, .21, .30))),
    "arcade": ("arcade", ((523, .12, .045), (659, .12, .045),
                          (784, .12, .045), (1047, .26, .12),
                          (784, .12, .045), (1047, .32, .15))),
    "sparkle": ("sparkle", ((1047, .18, .07), (1319, .18, .07),
                            (1568, .21, .10), (1175, .19, .07),
                            (1568, .39, .17))),
    "melody": ("warm", ((392, .30, .05), (440, .30, .05),
                        (523, .40, .06), (440, .28, .05),
                        (659, .45, .10), (523, .42, .16))),
    "urgent": ("urgent", ((740, .22, .11), (988, .22, .11),
                          (740, .22, .11), (988, .22, .11),
                          (740, .22, .11), (988, .37, .23))),
}


def _klank(soort: str, fase: float, t: float, lengte: float) -> float:
    """Combineer een paar boventonen, met een percussieve afname waar passend."""
    basis = math.sin(fase)
    if soort == "bell":
        return (0.66 * basis + 0.23 * math.sin(fase * 2.01)
                + 0.11 * math.sin(fase * 3.92)) * math.exp(-1.3 * t / lengte)
    if soort == "piano":
        return (0.78 * basis + 0.17 * math.sin(fase * 2.0)
                + 0.05 * math.sin(fase * 3.0)) * math.exp(-1.8 * t / lengte)
    if soort == "marimba":
        return (0.73 * basis + 0.27 * math.sin(fase * 2.04)) * math.exp(-3.1 * t / lengte)
    if soort == "radar":
        return 0.89 * basis + 0.11 * math.sin(fase * 2.0)
    if soort == "pulse":
        return 0.84 * basis + 0.16 * math.sin(fase * 2.0)
    if soort == "arcade":
        return 0.66 * basis + 0.22 * math.sin(fase * 3.0) + 0.12 * math.sin(fase * 5.0)
    if soort == "sparkle":
        return (0.80 * basis + 0.20 * math.sin(fase * 2.02)) * math.exp(-1.5 * t / lengte)
    if soort == "urgent":
        return 0.75 * basis + 0.25 * math.sin(fase * 2.0)
    return 0.90 * basis + 0.10 * math.sin(fase * 2.0)


def maak_melodie_wav(geluid: str, volume: int) -> bytes:
    """Maak één hoorbare frase; de bestaande AplaySpeaker verzorgt het herhalen."""
    if geluid not in _MELODIES:
        raise ValueError(f"Onbekend melodiegeluid: {geluid}")
    if type(volume) is not int or not 0 <= volume <= 100:
        raise ValueError("Volume moet een geheel getal van 0 t/m 100 zijn")

    soort, noten = _MELODIES[geluid]
    gain = .42 * (volume / 100) ** 1.6
    pcm = bytearray()
    for frequentie, duur, stilte in noten:
        noot_samples = round(duur * SAMPLE_RATE)
        attack = min(.018, duur / 5)
        release = min(.048, duur / 4)
        for i in range(noot_samples):
            t = i / SAMPLE_RATE
            env = max(0., min(1., t / attack, (duur - t) / release))
            if soort == "radar":
                # Een lichte sweep geeft het radarsignaal zijn eigen karakter.
                fase = 2 * math.pi * (frequentie * t + 65 * t * t)
            else:
                fase = 2 * math.pi * frequentie * t
            waarde = gain * env * _klank(soort, fase, t, duur)
            pcm.extend(struct.pack("<h", int(max(-1., min(1., waarde)) * 32767)))
        pcm.extend(b"\x00\x00" * round(stilte * SAMPLE_RATE))

    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm)
    return stream.getvalue()
