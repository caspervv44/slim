"""Vaste WakeSync-alarmgeluiden, gedeeld door GUI en audiogenerator.

De sleutels zijn stabiel: ze staan per alarm in het bestaande JSON-instellingenbestand.
Geen muziekdownloads, auteursrechtelijke opnames of extra Python-pakketten nodig.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlarmSound:
    key: str
    label: str
    beschrijving: str


ALARM_SOUNDS: tuple[AlarmSound, ...] = (
    AlarmSound("beep", "Basisbeep", "Helder en eenvoudig"),
    AlarmSound("classic", "Klassiek", "Traditioneel alarm"),
    AlarmSound("soft", "Zacht", "Rustig opstarten"),
    AlarmSound("digital", "Digitaal", "Korte elektronische tonen"),
    AlarmSound("sunrise", "Ochtendglans", "Opgaande melodie"),
    AlarmSound("chime", "Klokkenspel", "Helder en vriendelijk"),
    AlarmSound("piano", "Piano", "Warme pianotonen"),
    AlarmSound("marimba", "Marimba", "Houten klank"),
    AlarmSound("bells", "Klokken", "Diep en rond"),
    AlarmSound("radar", "Radar", "Ritmische signalen"),
    AlarmSound("pulse", "Hartslag", "Dubbele pulsen"),
    AlarmSound("arcade", "Arcade", "Retro spelgeluid"),
    AlarmSound("sparkle", "Sterren", "Lichte hoge noten"),
    AlarmSound("melody", "Melodie", "Vrolijk wijsje"),
    AlarmSound("urgent", "Energiek", "Extra opvallend"),
)
ALARM_SOUND_IDS = tuple(sound.key for sound in ALARM_SOUNDS)
_ALARM_SOUND_BY_ID = {sound.key: sound for sound in ALARM_SOUNDS}


def sound_label(key: str) -> str:
    """Geef een leesbare naam; een onbekende oude instelling blijft herkenbaar."""
    entry = _ALARM_SOUND_BY_ID.get(str(key))
    return entry.label if entry is not None else str(key or "beep").capitalize()
