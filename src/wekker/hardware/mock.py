"""Mock-hardware voor laptop en tests.

Elke mock houdt zijn toestand bij (lamp aan? welk geluid? welke
displaytekst?) en kan events simuleren (``press()``). MockMotor en
MockTouchSensor blijven behouden voor een latere prototypefase, maar het
eerste prototype gebruikt ze niet.
"""

from __future__ import annotations

from typing import Callable, Sequence


class MockDisplay:
    """Nepdisplay: onthoudt de laatst getoonde regels."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.brightness: int = 80
        self.cleared: bool = True

    def show(self, lines: Sequence[str]) -> None:
        self.lines = list(lines)
        self.cleared = False

    def clear(self) -> None:
        self.lines = []
        self.cleared = True

    def set_brightness(self, level: int) -> None:
        if not 0 <= level <= 100:
            raise ValueError("brightness 0..100")
        self.brightness = level

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class MockSpeaker:
    def __init__(self) -> None:
        self.current_sound: str | None = None
        self.current_volume: int = 0

    def play(self, sound: str, volume: int) -> None:
        if not sound:
            raise ValueError("sound mag niet leeg zijn")
        if not 0 <= volume <= 100:
            raise ValueError("volume 0..100")
        self.current_sound = sound
        self.current_volume = volume

    def stop(self) -> None:
        self.current_sound = None
        self.current_volume = 0

    @property
    def is_playing(self) -> bool:
        return self.current_sound is not None


class MockLamp:
    def __init__(self) -> None:
        self.brightness: int = 0
        self.blink: bool = False
        self.pattern: str = "steady"
        self._on: bool = False

    def on(self, brightness: int, blink: bool = False, pattern: str = "steady") -> None:
        if not 0 <= brightness <= 100:
            raise ValueError("brightness 0..100")
        self._on = True
        self.brightness = brightness
        self.blink = blink
        self.pattern = pattern

    def off(self) -> None:
        self._on = False
        self.brightness = 0
        self.blink = False

    @property
    def is_on(self) -> bool:
        return self._on


class MockButton:
    """Simuleer een fysieke knop via ``press()``."""

    def __init__(self) -> None:
        self._handlers: list[Callable[[], None]] = []
        self.press_count: int = 0

    def on_press(self, handler: Callable[[], None]) -> None:
        self._handlers.append(handler)

    def press(self) -> None:
        self.press_count += 1
        for handler in list(self._handlers):
            handler()


class MockTouchSensor:
    """Simuleer oppakken/aanraken via ``touch()``."""

    def __init__(self) -> None:
        self._handlers: list[Callable[[], None]] = []
        self.touch_count: int = 0

    def on_touch(self, handler: Callable[[], None]) -> None:
        self._handlers.append(handler)

    def touch(self) -> None:
        self.touch_count += 1
        for handler in list(self._handlers):
            handler()


class MockMotor:
    def __init__(self) -> None:
        self.target: str | None = None

    def drive_to(self, target: str) -> None:
        if not target:
            raise ValueError("target mag niet leeg zijn")
        self.target = target

    def stop(self) -> None:
        self.target = None

    @property
    def is_driving(self) -> bool:
        return self.target is not None
