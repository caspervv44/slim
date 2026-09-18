"""Touchscreen-schermen als pure logica (geen tkinter hier).

Dit moduletje beschrijft *wat* er op het 800x480-scherm staat als data
(layout-dicts); ``wekker.gui.app`` rendert die naar tkinter-widgets. Zo is
alle schermlogica en navigatie headless te testen, en kan later echte
Osiris-data gebruikt worden zonder GUI-refactor: alleen de data verandert.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

#: Fysieke resolutie van het 5-inch touchscreen.
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 480

#: Maximaal aantal lessen op het agendescherm (rustig ontwerp, grote tekst).
AGENDA_MAX_ROWS = 5


class ScreenId(str, Enum):
    MAIN = "main"
    AGENDA = "agenda"


class Navigator:
    """Schermvolgorde + pijl-navigatie. Uitbreidbaar: registreer extra
    schermen en links/rechts bladert er automatisch doorheen (wrap)."""

    def __init__(self, screens: list[ScreenId] | None = None) -> None:
        self._order: list[ScreenId] = list(screens) if screens is not None else [
            ScreenId.MAIN, ScreenId.AGENDA,
        ]
        if not self._order:
            raise ValueError("Navigator heeft minimaal één scherm nodig")
        self._index = 0

    @property
    def current(self) -> ScreenId:
        return self._order[self._index]

    def register(self, screen: ScreenId) -> None:
        """Voeg een scherm toe (later: instellingen, status, ...)."""
        if screen not in self._order:
            self._order.append(screen)

    def go(self, screen: ScreenId) -> ScreenId:
        self._index = self._order.index(screen)
        return self.current

    def go_left(self) -> ScreenId:
        self._index = (self._index - 1) % len(self._order)
        return self.current

    def go_right(self) -> ScreenId:
        self._index = (self._index + 1) % len(self._order)
        return self.current


def format_time(moment: datetime) -> str:
    """Grote klokweergave, bv. ``07:32``."""
    return moment.strftime("%H:%M")


def format_alarm(next_alarm: datetime | None) -> str:
    """Alarmtijd of ``uit`` als er geen volgend alarm is."""
    return next_alarm.strftime("%H:%M") if next_alarm else "uit"


@dataclass(frozen=True)
class MainScreenData:
    time_str: str
    alarm_str: str


@dataclass(frozen=True)
class AgendaRow:
    time_str: str
    subject: str


@dataclass(frozen=True)
class AgendaScreenData:
    provider_name: str
    day_label: str
    rows: tuple[AgendaRow, ...] = ()
    simulated: bool = True


@dataclass
class GuiData:
    """Momentopname voor één render-slag (gebouwd uit Runtime in app.py)."""

    main: MainScreenData
    agenda: AgendaScreenData
    notices: tuple[str, ...] = ()


def build_main_data(now: datetime, next_alarm: datetime | None) -> MainScreenData:
    return MainScreenData(time_str=format_time(now), alarm_str=format_alarm(next_alarm))


def build_agenda_data(lessons: list, provider_name: str,
                      day_label: str = "Vandaag") -> AgendaScreenData:
    """Map generieke lessen (Lesson) naar agenda-regels. Werkt voor elke
    provider: mock, Osiris-demo en later echte Osiris-data."""
    from wekker.agenda.models import SIMULATED_SOURCES

    rows = tuple(
        AgendaRow(time_str=les.start.strftime("%H:%M"), subject=les.subject)
        for les in sorted(lessons, key=lambda les: les.start)[:AGENDA_MAX_ROWS]
    )
    simulated = all(les.source in SIMULATED_SOURCES for les in lessons) if lessons else True
    return AgendaScreenData(provider_name=provider_name, day_label=day_label,
                            rows=rows, simulated=simulated)


def _nav_button(label: str, target: ScreenId) -> dict:
    return {"label": label, "target": target.value}


def main_layout(data: MainScreenData) -> dict:
    """Layout hoofscherm: grote tijd, alarmtijd, pijlen links/rechts."""
    return {
        "screen": ScreenId.MAIN.value,
        "time": data.time_str,
        "alarm_label": "Alarm",
        "alarm": data.alarm_str,
        "left": _nav_button("<", ScreenId.AGENDA),
        "right": _nav_button(">", ScreenId.AGENDA),
    }


def agenda_layout(data: AgendaScreenData) -> dict:
    """Layout agendescherm: provider, dag, lessen, mock-badge, terug-pijl."""
    return {
        "screen": ScreenId.AGENDA.value,
        "title": data.provider_name,
        "day": data.day_label,
        "rows": [{"time": r.time_str, "subject": r.subject} for r in data.rows],
        "empty_text": "Geen lessen vandaag" if not data.rows else "",
        "simulated": data.simulated,
        "left": _nav_button("<", ScreenId.MAIN),
        "right": _nav_button(">", ScreenId.MAIN),
    }


def layout_for(navigator: Navigator, data: GuiData) -> dict:
    """Layout voor het actieve scherm (aangestuurd door de Navigator)."""
    if navigator.current is ScreenId.AGENDA:
        return agenda_layout(data.agenda)
    return main_layout(data.main)
