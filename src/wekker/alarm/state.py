"""Alarmtoestanden (eerste prototype).

Bewegingshardware is uitgesteld naar een latere prototypefase; er is daarom
geen fysieke-alarmtoestand in deze versie.
"""

from enum import Enum


class AlarmState(str, Enum):
    SLEEPING = "sleeping"
    RINGING = "ringing"
    SNOOZED = "snoozed"
    DISMISSED = "dismissed"
