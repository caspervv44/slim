"""Touchscreen-schermen als pure logica (geen tkinter hier).

Dit module beschrijft *wat* er op het 800x480-scherm staat als data.
``wekker.gui.app`` rendert die data naar tkinter-widgets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

SCREEN_WIDTH = 800
SCREEN_HEIGHT = 480
AGENDA_MAX_ROWS = 5

DUTCH_MONTHS = (
    "", "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december",
)
DUTCH_WEEKDAYS = (
    "Maandag", "Dinsdag", "Woensdag", "Donderdag",
    "Vrijdag", "Zaterdag", "Zondag",
)


class ScreenId(str, Enum):
    MAIN = "main"
    AGENDA = "agenda"
    SETTINGS = "settings"


class Navigator:
    """Schermvolgorde voor de drie lokale klokpagina's."""

    def __init__(self, screens: list[ScreenId] | None = None) -> None:
        self._order: list[ScreenId] = list(screens) if screens is not None else [
            ScreenId.MAIN, ScreenId.AGENDA, ScreenId.SETTINGS,
        ]
        if not self._order:
            raise ValueError("Navigator heeft minimaal één scherm nodig")
        self._index = 0

    @property
    def current(self) -> ScreenId:
        return self._order[self._index]

    def register(self, screen: ScreenId) -> None:
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


def format_time(moment: datetime, time_format: str = "24h") -> str:
    """Formatteer de klok in 24-uurs- of 12-uursweergave."""
    if time_format == "12h":
        # Linux/Pi ondersteunt %-I; door handmatig te formatteren werkt dit
        # ook op andere Python-platforms zonder voorloopnul.
        hour = moment.hour % 12 or 12
        suffix = "AM" if moment.hour < 12 else "PM"
        return f"{hour}:{moment.minute:02d} {suffix}"
    return moment.strftime("%H:%M")


def format_alarm(next_alarm: datetime | None, time_format: str = "24h") -> str:
    return format_time(next_alarm, time_format) if next_alarm else "uit"


def format_day_label(day: date, today: date) -> str:
    """Nederlandse kop voor de gekozen agendadag."""
    datum = f"{day.day} {DUTCH_MONTHS[day.month]}"
    if day == today:
        return f"Vandaag - {datum}"
    return f"{DUTCH_WEEKDAYS[day.weekday()]} - {datum}"


@dataclass(frozen=True)
class MainScreenData:
    time_str: str
    alarm_str: str


@dataclass(frozen=True)
class AgendaRow:
    # ``time_str`` blijft de starttijd heten voor backwards compatibility.
    time_str: str
    subject: str
    end_str: str = ""
    room: str = ""
    teacher: str = ""

    @property
    def start_str(self) -> str:
        return self.time_str


@dataclass(frozen=True)
class AgendaScreenData:
    provider_name: str
    day_label: str
    rows: tuple[AgendaRow, ...] = ()
    simulated: bool = True


@dataclass(frozen=True)
class SettingsScreenData:
    """Alleen lokale scherminstellingen; MyX-configuratie blijft in de webapp."""

    timezone: str = "Europe/Amsterdam"
    time_format: str = "24h"
    region: str = "NL"
    # Oude velden blijven als compatibiliteitsmarge aanwezig, maar worden
    # bewust nergens op het lokale instellingen-scherm getoond.
    provider: str = "mock"
    linked: bool = False
    token_valid: bool = False
    busy: bool = False
    account: str = ""
    error: str = ""
    cloud_ready: bool = False
    cloud_url: str = ""
    cloud_username: str = "basis"
    cloud_password: str = ""
    cloud_password_changed: bool = False
    cloud_status: str = "Cloudkoppeling voorbereiden…"
    cloud_error: str = ""


@dataclass
class GuiData:
    main: MainScreenData
    agenda: AgendaScreenData
    settings: SettingsScreenData = SettingsScreenData()
    notices: tuple[str, ...] = ()


def build_main_data(
    now: datetime,
    next_alarm: datetime | None,
    time_format: str = "24h",
) -> MainScreenData:
    return MainScreenData(
        time_str=format_time(now, time_format),
        alarm_str=format_alarm(next_alarm, time_format),
    )


def build_agenda_data(
    lessons: list,
    provider_name: str,
    day_label: str = "Vandaag",
) -> AgendaScreenData:
    """Map generieke lessen naar compacte maar volledige agenda-regels."""
    from wekker.agenda.models import SIMULATED_SOURCES

    rows = tuple(
        AgendaRow(
            time_str=les.start.strftime("%H:%M"),
            end_str=les.end.strftime("%H:%M"),
            subject=les.subject,
            room=les.room or "",
            teacher=les.teacher or "",
        )
        for les in sorted(lessons, key=lambda les: les.start)[:AGENDA_MAX_ROWS]
    )
    simulated = all(les.source in SIMULATED_SOURCES for les in lessons) if lessons else True
    return AgendaScreenData(
        provider_name=provider_name,
        day_label=day_label,
        rows=rows,
        simulated=simulated,
    )


def _nav_button(label: str, target: ScreenId) -> dict:
    return {"label": label, "target": target.value}


def main_layout(data: MainScreenData) -> dict:
    return {
        "screen": ScreenId.MAIN.value,
        "time": data.time_str,
        "alarm_label": "Alarm",
        "alarm": data.alarm_str,
        "left": _nav_button("<", ScreenId.SETTINGS),
        "right": _nav_button(">", ScreenId.AGENDA),
    }


def agenda_layout(data: AgendaScreenData) -> dict:
    return {
        "screen": ScreenId.AGENDA.value,
        "title": data.provider_name,
        "provider": data.provider_name,
        "day": data.day_label,
        "rows": [
            {
                "start": row.start_str,
                "end": row.end_str,
                "time": row.start_str,
                "subject": row.subject,
                "room": row.room,
                "teacher": row.teacher,
            }
            for row in data.rows
        ],
        "empty_text": "Geen lessen op deze dag" if not data.rows else "",
        "simulated": data.simulated,
        "left": _nav_button("<", ScreenId.MAIN),
        "right": _nav_button(">", ScreenId.SETTINGS),
    }


def settings_layout(data: SettingsScreenData) -> dict:
    return {
        "screen": ScreenId.SETTINGS.value,
        "title": "Instellingen",
        "timezone": data.timezone,
        "time_format": data.time_format,
        "region": data.region,
        "cloud_ready": data.cloud_ready,
        "cloud_url": data.cloud_url,
        "cloud_username": data.cloud_username,
        "cloud_password": data.cloud_password,
        "cloud_password_changed": data.cloud_password_changed,
        "cloud_status": data.cloud_status,
        "cloud_error": data.cloud_error,
        "left": _nav_button("<", ScreenId.AGENDA),
        "right": _nav_button(">", ScreenId.MAIN),
    }


def layout_for(navigator: Navigator, data: GuiData) -> dict:
    if navigator.current is ScreenId.AGENDA:
        return agenda_layout(data.agenda)
    if navigator.current is ScreenId.SETTINGS:
        return settings_layout(data.settings)
    return main_layout(data.main)
