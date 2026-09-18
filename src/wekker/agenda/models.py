"""Intern agendamodel. Elke schooladapter vertaalt hierheen."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Lesson:
    subject: str
    start: datetime
    end: datetime
    teacher: str = ""
    room: str = ""
    # Herkomst van de gegevens ("mock" = gesimuleerd; later per platform).
    # De setup-app toont dit zodat nooit echte en nepgegevens verward worden.
    source: str = "mock"

    def to_dict(self) -> dict:
        """Serialiseer voor de setup-API (gesimuleerd-badge via 'simulated')."""
        return {
            "title": self.subject,
            "subject": self.subject,
            "start_time": self.start.isoformat(),
            "end_time": self.end.isoformat(),
            "location": self.room,
            "teacher": self.teacher,
            "source": self.source,
            "simulated": self.source == "mock",
        }

    def __post_init__(self) -> None:
        if not self.subject:
            raise ValueError("subject mag niet leeg zijn")
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("start/end moeten timezone-aware zijn")
        if self.end <= self.start:
            raise ValueError("end moet na start liggen")
        if self.start.date() != self.end.date():
            raise ValueError("les moet binnen één dag vallen")


@dataclass
class DaySchedule:
    day: date
    lessons: list[Lesson]

    def __post_init__(self) -> None:
        self.lessons = sorted(self.lessons, key=lambda les: les.start)
        for les in self.lessons:
            if les.start.date() != self.day:
                raise ValueError("les valt niet op de dag van het rooster")

    @property
    def first(self) -> Lesson | None:
        return self.lessons[0] if self.lessons else None

    @property
    def last(self) -> Lesson | None:
        return self.lessons[-1] if self.lessons else None
