"""Intern agendamodel. Elke schooladapter vertaalt hierheen."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

#: Bronlabels waarvan de gegevens altijd gesimuleerd zijn. Echte
#: platformdata krijgt de kale providernaam als source (bv. "myx").
SIMULATED_SOURCES = frozenset({"mock", "osiris-demo"})


@dataclass(frozen=True)
class Lesson:
    subject: str
    start: datetime
    end: datetime
    teacher: str = ""
    room: str = ""
    source: str = "mock"

    def to_dict(self) -> dict:
        """Serialiseer voor API en persistente cache."""
        return {
            "title": self.subject,
            "subject": self.subject,
            "start_time": self.start.isoformat(),
            "end_time": self.end.isoformat(),
            "location": self.room,
            "teacher": self.teacher,
            "source": self.source,
            "simulated": self.source in SIMULATED_SOURCES,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Lesson":
        """Herstel een les uit de persistente agenda-cache."""
        if not isinstance(data, dict):
            raise ValueError("lesrecord moet een object zijn")
        return cls(
            subject=str(data.get("subject") or data.get("title") or ""),
            start=datetime.fromisoformat(str(data["start_time"])),
            end=datetime.fromisoformat(str(data["end_time"])),
            teacher=str(data.get("teacher") or ""),
            room=str(data.get("location") or data.get("room") or ""),
            source=str(data.get("source") or "mock"),
        )

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

    def to_dict(self) -> dict:
        return {
            "day": self.day.isoformat(),
            "lessons": [lesson.to_dict() for lesson in self.lessons],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DaySchedule":
        if not isinstance(data, dict):
            raise ValueError("dagrooster moet een object zijn")
        records = data.get("lessons", [])
        if not isinstance(records, list):
            raise ValueError("lessons moet een lijst zijn")
        return cls(
            day=date.fromisoformat(str(data["day"])),
            lessons=[Lesson.from_dict(item) for item in records],
        )

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
