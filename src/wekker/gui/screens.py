"""Pure schermmodellen voor het 800×480 WakeSync-touchscreen."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
import math

SCREEN_WIDTH = 800
SCREEN_HEIGHT = 480
AGENDA_PAGE_SIZE = 4
# Oude naam blijft importeerbaar; de limiet geldt nu per pagina, niet per dag.
AGENDA_MAX_ROWS = AGENDA_PAGE_SIZE

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
    def __init__(self, screens: list[ScreenId] | None = None) -> None:
        self._order = list(screens) if screens is not None else [
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
    if time_format == "12h":
        hour = moment.hour % 12 or 12
        suffix = "AM" if moment.hour < 12 else "PM"
        return f"{hour}:{moment.minute:02d} {suffix}"
    return moment.strftime("%H:%M")


def format_alarm(next_alarm: datetime | None, time_format: str = "24h") -> str:
    return format_time(next_alarm, time_format) if next_alarm else "uit"


def format_alarm_day(next_alarm: datetime | None, today: date) -> str:
    if next_alarm is None:
        return "Alarm uit"
    delta = (next_alarm.date() - today).days
    if delta == 0:
        day = "Vandaag"
    elif delta == 1:
        day = "Morgen"
    else:
        day = DUTCH_WEEKDAYS[next_alarm.weekday()]
    return day


def format_day_label(day: date, today: date) -> str:
    datum = f"{day.day} {DUTCH_MONTHS[day.month]}"
    if day == today:
        return f"Vandaag - {datum}"
    return f"{DUTCH_WEEKDAYS[day.weekday()]} - {datum}"


@dataclass(frozen=True)
class MainScreenData:
    time_str: str
    alarm_str: str
    alarm_day: str = ""
    lesson_label: str = "ROOSTER"
    lesson_subject: str = "Nog niet geladen"
    lesson_time: str = ""
    lesson_room: str = "—"
    lesson_teacher: str = ""
    agenda_status: str = "Nog niet geladen"
    notice: str = ""


@dataclass(frozen=True)
class AgendaRow:
    time_str: str
    subject: str
    end_str: str = ""
    room: str = ""
    teacher: str = ""
    relation_before: str = ""
    current: bool = False

    @property
    def start_str(self) -> str:
        return self.time_str


@dataclass(frozen=True)
class AgendaScreenData:
    provider_name: str
    day_label: str
    rows: tuple[AgendaRow, ...] = ()
    simulated: bool = True
    page: int = 0
    page_count: int = 1
    total_rows: int = 0
    loaded: bool = False
    status_text: str = "Nog niet geladen"
    empty_text: str = ""


@dataclass(frozen=True)
class SettingsScreenData:
    timezone: str = "Europe/Amsterdam"
    time_format: str = "24h"
    region: str = "NL"
    theme: str = "midnight"
    sleep_after_seconds: int = 60
    sleep_view: str = "logo_time_date"
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
    cloud_revision: int = 0
    cloud_last_sync: str = ""


@dataclass
class GuiData:
    main: MainScreenData
    agenda: AgendaScreenData
    settings: SettingsScreenData = SettingsScreenData()
    notices: tuple[str, ...] = ()


def _lesson_summary(now: datetime, lessons: list, loaded: bool) -> tuple[str, str, str, str, str]:
    if not loaded:
        return "ROOSTER", "Nog niet geladen", "", "—", ""
    ordered = sorted(lessons, key=lambda lesson: lesson.start)
    current = next((lesson for lesson in ordered if lesson.start <= now < lesson.end), None)
    if current is not None:
        return (
            "HUIDIGE LES",
            current.subject,
            f"{current.start:%H:%M} – {current.end:%H:%M}",
            current.room or "—",
            current.teacher or "",
        )
    upcoming = next((lesson for lesson in ordered if lesson.start > now), None)
    if upcoming is not None:
        return (
            "VOLGENDE LES",
            upcoming.subject,
            f"{upcoming.start:%H:%M} – {upcoming.end:%H:%M}",
            upcoming.room or "—",
            upcoming.teacher or "",
        )
    return "VANDAAG", "Geen lessen meer", "", "—", ""


def build_main_data(
    now: datetime,
    next_alarm: datetime | None,
    time_format: str = "24h",
    *,
    lessons: list | None = None,
    agenda_loaded: bool = False,
    agenda_status: str = "Nog niet geladen",
    notice: str = "",
) -> MainScreenData:
    label, subject, time_text, room, teacher = _lesson_summary(
        now, lessons or [], agenda_loaded
    )
    return MainScreenData(
        time_str=format_time(now, time_format),
        alarm_str=format_alarm(next_alarm, time_format),
        alarm_day=format_alarm_day(next_alarm, now.date()),
        lesson_label=label,
        lesson_subject=subject,
        lesson_time=time_text,
        lesson_room=room,
        lesson_teacher=teacher,
        agenda_status=agenda_status,
        notice=notice,
    )


def build_agenda_data(
    lessons: list,
    provider_name: str,
    day_label: str = "Vandaag",
    *,
    page: int = 0,
    now: datetime | None = None,
    loaded: bool = True,
    status_text: str = "",
) -> AgendaScreenData:
    """Map een volledige dag naar één pagina zonder lessen weg te gooien."""
    from wekker.agenda.models import SIMULATED_SOURCES

    ordered = sorted(lessons, key=lambda lesson: lesson.start)
    page_count = max(1, math.ceil(len(ordered) / AGENDA_PAGE_SIZE))
    page = max(0, min(int(page), page_count - 1))

    rows_all: list[AgendaRow] = []
    previous = None
    for lesson in ordered:
        relation = ""
        if previous is not None:
            if lesson.start < previous.end:
                relation = "OVERLAP"
            else:
                gap = lesson.start - previous.end
                minutes = int(gap.total_seconds() // 60)
                if minutes >= 10:
                    relation = f"PAUZE {minutes} MIN"
        rows_all.append(
            AgendaRow(
                time_str=lesson.start.strftime("%H:%M"),
                end_str=lesson.end.strftime("%H:%M"),
                subject=lesson.subject,
                room=lesson.room or "",
                teacher=lesson.teacher or "",
                relation_before=relation,
                current=bool(
                    now is not None
                    and lesson.start.date() == now.date()
                    and lesson.start <= now < lesson.end
                ),
            )
        )
        previous = lesson

    start = page * AGENDA_PAGE_SIZE
    page_rows = tuple(rows_all[start:start + AGENDA_PAGE_SIZE])
    simulated = (
        all(lesson.source in SIMULATED_SOURCES for lesson in ordered)
        if ordered else False
    )
    if not loaded:
        empty_text = "Nog niet geladen"
    elif not ordered:
        empty_text = "Geen lessen op deze dag"
    else:
        empty_text = ""

    return AgendaScreenData(
        provider_name=provider_name,
        day_label=day_label,
        rows=page_rows,
        simulated=simulated,
        page=page,
        page_count=page_count,
        total_rows=len(ordered),
        loaded=loaded,
        status_text=status_text,
        empty_text=empty_text,
    )


def _nav_button(label: str, target: ScreenId) -> dict:
    return {"label": label, "target": target.value}


def main_layout(data: MainScreenData) -> dict:
    return {
        "screen": ScreenId.MAIN.value,
        "time": data.time_str,
        "alarm_label": "VOLGEND ALARM",
        "alarm": data.alarm_str,
        "alarm_day": data.alarm_day,
        "lesson_label": data.lesson_label,
        "lesson_subject": data.lesson_subject,
        "lesson_time": data.lesson_time,
        "lesson_room": data.lesson_room,
        "lesson_teacher": data.lesson_teacher,
        "agenda_status": data.agenda_status,
        "notice": data.notice,
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
                "relation_before": row.relation_before,
                "current": row.current,
            }
            for row in data.rows
        ],
        "empty_text": data.empty_text,
        "simulated": data.simulated,
        "page": data.page,
        "page_count": data.page_count,
        "total_rows": data.total_rows,
        "loaded": data.loaded,
        "status_text": data.status_text,
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
        "theme": data.theme,
        "sleep_after_seconds": data.sleep_after_seconds,
        "sleep_view": data.sleep_view,
        "cloud_ready": data.cloud_ready,
        "cloud_url": data.cloud_url,
        "cloud_username": data.cloud_username,
        "cloud_password": data.cloud_password,
        "cloud_password_changed": data.cloud_password_changed,
        "cloud_status": data.cloud_status,
        "cloud_error": data.cloud_error,
        "cloud_revision": data.cloud_revision,
        "cloud_last_sync": data.cloud_last_sync,
        "left": _nav_button("<", ScreenId.AGENDA),
        "right": _nav_button(">", ScreenId.MAIN),
    }


def layout_for(navigator: Navigator, data: GuiData) -> dict:
    if navigator.current is ScreenId.AGENDA:
        return agenda_layout(data.agenda)
    if navigator.current is ScreenId.SETTINGS:
        return settings_layout(data.settings)
    return main_layout(data.main)
