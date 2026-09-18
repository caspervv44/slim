"""Abstracte hardware-interfaces (Protocols).

Regel: de wekker-core importeert GPIO/drivers nooit direct. Op de laptop
worden de mocks uit ``wekker.hardware.mock`` gebruikt; op de Pi komt er een
``wekker.hardware.raspberry`` module met dezelfde methodenamen. GPIO-pinnen
liggen pas vast zodra de hardwarekeuze definitief is — zie docs/architecture.

Contract voor echte drivers:
- Alle methoden moeten herhaalde aanroepen tolereren (de core probeert een
  mislukte transitie de volgende seconde opnieuw, dus ``play``/``on``/
  ``drive_to`` moet idempotent zijn).
- Methoden mogen gooien bij hardwarefouten; de wekkerlus vangt dit op en de
  core houdt dan zijn oude toestand. Slik fouten nooit stil weg.
"""

from __future__ import annotations

from typing import Callable, Protocol, Sequence


class DisplayDriver(Protocol):
    def show(self, lines: Sequence[str]) -> None: ...
    def clear(self) -> None: ...
    def set_brightness(self, level: int) -> None: ...


class Speaker(Protocol):
    def play(self, sound: str, volume: int) -> None: ...
    def stop(self) -> None: ...
    @property
    def is_playing(self) -> bool: ...


class Lamp(Protocol):
    def on(self, brightness: int, blink: bool = False, pattern: str = "steady") -> None: ...
    def off(self) -> None: ...
    @property
    def is_on(self) -> bool: ...


class Button(Protocol):
    def on_press(self, handler: Callable[[], None]) -> None: ...


class TouchSensor(Protocol):
    """UITGESTELD: maakt geen deel uit van het eerste prototype.

    Het protocol blijft behouden voor een latere fase; nieuwe code mag er
    niet van afhankelijk zijn tot touchhardware is gekozen en getest.
    """

    def on_touch(self, handler: Callable[[], None]) -> None: ...


class MotorController(Protocol):
    """UITGESTELD: bewegingshardware hoort bij een latere prototypefase.

    Het protocol blijft behouden voor later; het eerste prototype start
    zonder motoren en nieuwe code mag hier niet van afhankelijk zijn.
    """

    def drive_to(self, target: str) -> None: ...
    def stop(self) -> None: ...
    @property
    def is_driving(self) -> bool: ...
