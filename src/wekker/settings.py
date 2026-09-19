"""Instellingen met validatie. Geen geheimen in deze structuur.

Beveiligingsregel: wachtwoorden en tokens worden hier nooit opgeslagen.
De agenda-adapters krijgen later alleen een providernaam + verwijzing naar
een veilige opslag (bv. OS-keyring op de Pi). Logs mogen nooit de inhoud
van een geheim tonen — zie ``logging_config``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

ALLOWED_VISIBLE_FIELDS = frozenset(
    {
        "time",
        "next_alarm",
        "first_lesson",
        "teacher",
        "room",
        "last_lesson",
        "day_agenda",
        "appointments",
    }
)
ALLOWED_BLINK_PATTERNS = frozenset({"steady", "blink", "pulse"})
ALLOWED_NIGHT_MODES = frozenset({"off", "dim"})
#: Schoolplatformen die de setup-app mag aanbieden. Alleen "mock" heeft een
#: werkende adapter; de rest is voorbereid maar "nog niet beschikbaar".
ALLOWED_PROVIDERS = frozenset({"mock", "magister", "somtoday", "osiris", "myx"})
#: Standaardtijdzone van de wekker (Nederland). DST wordt automatisch door
#: zoneinfo afgehandeld; er wordt nergens een vaste UTC-offset gehanteerd.
DEFAULT_TIMEZONE = "Europe/Amsterdam"
#: Standaardregio (ISO 3166-1 alpha-2).
DEFAULT_REGION = "NL"


class SettingsError(ValueError):
    """Ongeldige instellingwaarde."""


def _check_time(value: str, veld: str) -> str:
    try:
        uur, minuut = value.split(":")
        h, m = int(uur), int(minuut)
    except (ValueError, AttributeError) as exc:
        raise SettingsError(f"{veld} moet 'HH:MM' zijn, kreeg {value!r}") from exc
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise SettingsError(f"{veld} moet 'HH:MM' zijn, kreeg {value!r}")
    return f"{h:02d}:{m:02d}"


def _check_bool(value: bool, veld: str) -> bool:
    # Strikt: JSON true/false worden Python-bools. Strings ("false") of
    # integers (0/1) zijn altijd een typefout en worden geweigerd, omdat een
    # verkeerd geïnterpreteerde vlag het alarm stil kan zetten.
    if not isinstance(value, bool):
        raise SettingsError(f"{veld} moet true of false zijn, kreeg {value!r}")
    return value


def _check_range(value: int, veld: str, low: int, high: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise SettingsError(f"{veld} moet een geheel getal zijn")
    if not (low <= value <= high):
        raise SettingsError(f"{veld} moet tussen {low} en {high} liggen")
    return value


@dataclass
class AlarmSettings:
    time: str = "07:30"
    enabled: bool = True
    snooze_minutes: int = 9
    sound: str = "beep"
    volume: int = 70
    speaker_enabled: bool = True
    lamp_brightness: int = 100
    lamp_blink: bool = True
    blink_pattern: str = "blink"
    # Gereserveerd: nog niet toegepast door de core (zie docs/architecture.md).
    # Blijft instelbaar zodat de setup-app het veld al kan tonen.
    ramp_up_seconds: int = 30

    def __post_init__(self) -> None:
        self.time = _check_time(self.time, "alarm.time")
        self.enabled = _check_bool(self.enabled, "alarm.enabled")
        self.snooze_minutes = _check_range(self.snooze_minutes, "alarm.snooze_minutes", 1, 60)
        self.volume = _check_range(self.volume, "alarm.volume", 0, 100)
        self.speaker_enabled = _check_bool(self.speaker_enabled, "alarm.speaker_enabled")
        self.lamp_brightness = _check_range(
            self.lamp_brightness, "alarm.lamp_brightness", 0, 100
        )
        self.lamp_blink = _check_bool(self.lamp_blink, "alarm.lamp_blink")
        if self.blink_pattern not in ALLOWED_BLINK_PATTERNS:
            raise SettingsError(f"alarm.blink_pattern onbekend: {self.blink_pattern!r}")
        self.ramp_up_seconds = _check_range(
            self.ramp_up_seconds, "alarm.ramp_up_seconds", 0, 3600
        )
        if not self.sound or not isinstance(self.sound, str):
            raise SettingsError("alarm.sound moet een niet-lege naam zijn")


@dataclass
class LampSettings:
    """Lampgedrag voor het eerste prototype (eenvoudig aan/uit)."""

    duration_after_button: int = 30
    on_with_alarm: bool = True

    def __post_init__(self) -> None:
        self.duration_after_button = _check_range(
            self.duration_after_button, "lamp.duration_after_button", 1, 3600
        )
        self.on_with_alarm = _check_bool(self.on_with_alarm, "lamp.on_with_alarm")


@dataclass
class DisplaySettings:
    brightness: int = 80
    on_duration_seconds: int = 30
    night_mode: str = "dim"
    night_start: str = "23:00"
    night_end: str = "07:00"
    visible_fields: list[str] = field(
        default_factory=lambda: ["time", "next_alarm", "first_lesson", "teacher", "room"]
    )

    def __post_init__(self) -> None:
        self.brightness = _check_range(self.brightness, "display.brightness", 0, 100)
        self.on_duration_seconds = _check_range(
            self.on_duration_seconds, "display.on_duration_seconds", 1, 600
        )
        if self.night_mode not in ALLOWED_NIGHT_MODES:
            raise SettingsError(f"display.night_mode onbekend: {self.night_mode!r}")
        self.night_start = _check_time(self.night_start, "display.night_start")
        self.night_end = _check_time(self.night_end, "display.night_end")
        onbekend = set(self.visible_fields) - ALLOWED_VISIBLE_FIELDS
        if onbekend:
            raise SettingsError(f"display.visible_fields onbekend: {sorted(onbekend)}")
        if not self.visible_fields:
            raise SettingsError("display.visible_fields mag niet leeg zijn")


@dataclass
class AgendaSettings:
    provider: str = "mock"
    auto_sync_minutes: int = 15

    def __post_init__(self) -> None:
        self.auto_sync_minutes = _check_range(
            self.auto_sync_minutes, "agenda.auto_sync_minutes", 0, 1440
        )
        if self.provider not in ALLOWED_PROVIDERS:
            raise SettingsError(
                f"agenda.provider onbekend: {self.provider!r} "
                f"(kies uit {sorted(ALLOWED_PROVIDERS)})"
            )


@dataclass
class LocaleSettings:
    """Taal-/tijdinstellingen. De systeemklok blijft de bron van waarheid;
    deze sectie legt vast in welke zone de wekker hoort te draaien."""

    timezone: str = DEFAULT_TIMEZONE
    region: str = DEFAULT_REGION

    def __post_init__(self) -> None:
        self.timezone = _check_timezone(self.timezone)
        self.region = _check_region(self.region)


def _check_timezone(value: str) -> str:
    """Valideer een IANA-tijdzonenaam via zoneinfo (DST automatisch)."""
    if not isinstance(value, str) or not value:
        raise SettingsError(f"locale.timezone moet een naam zijn, kreeg {value!r}")
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    except ImportError as exc:
        raise SettingsError("zoneinfo niet beschikbaar op deze Python") from exc
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise SettingsError(f"locale.timezone onbekend: {value!r}") from exc
    return value


def _check_region(value: str) -> str:
    """Valideer een ISO 3166-1 alpha-2 regiocode (bv. 'NL')."""
    if not isinstance(value, str) or len(value) != 2 or not value.isalpha():
        raise SettingsError(f"locale.region moet een 2-lettercode zijn, kreeg {value!r}")
    return value.upper()


@dataclass
class Settings:
    alarm: AlarmSettings = field(default_factory=AlarmSettings)
    lamp: LampSettings = field(default_factory=LampSettings)
    display: DisplaySettings = field(default_factory=DisplaySettings)
    agenda: AgendaSettings = field(default_factory=AgendaSettings)
    locale: LocaleSettings = field(default_factory=LocaleSettings)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        if not isinstance(data, dict):
            raise SettingsError(
                f"Instellingen moeten een object zijn, kreeg {type(data).__name__}"
            )
        onbekend = set(data) - {"alarm", "lamp", "display", "agenda", "locale"}
        if onbekend:
            raise SettingsError(f"Onbekende secties: {sorted(onbekend)}")
        try:
            return cls(
                alarm=AlarmSettings(**data.get("alarm", {})),
                lamp=LampSettings(**data.get("lamp", {})),
                display=DisplaySettings(**data.get("display", {})),
                agenda=AgendaSettings(**data.get("agenda", {})),
                locale=LocaleSettings(**data.get("locale", {})),
            )
        except TypeError as exc:
            raise SettingsError(f"Onbekende instellingsleutel: {exc}") from exc

    def update_from_dict(self, patch: dict[str, Any]) -> Settings:
        """Valideer een gedeeltelijke update; atomic: bij fout verandert niets."""
        huidig = self.to_dict()
        for sectie, waarden in patch.items():
            if sectie not in huidig:
                raise SettingsError(f"Onbekende sectie: {sectie!r}")
            if not isinstance(waarden, dict):
                raise SettingsError(f"Sectie {sectie!r} moet een object zijn")
            for sleutel in waarden:
                if sleutel not in huidig[sectie]:
                    raise SettingsError(f"Onbekende sleutel: {sectie}.{sleutel}")
            merged = {**huidig[sectie], **waarden}
            huidig[sectie] = merged
        return Settings.from_dict(huidig)


def default_settings() -> Settings:
    return Settings()
