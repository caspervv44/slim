"""Hardware-interfaces. De core kent alleen deze Protocols."""

from wekker.hardware.interfaces import (
    Button,
    DisplayDriver,
    Lamp,
    MotorController,
    Speaker,
    TouchSensor,
)

__all__ = ["Button", "DisplayDriver", "Lamp", "MotorController", "Speaker", "TouchSensor"]
