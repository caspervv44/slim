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
ALLOWED_THEMES = frozenset({"midnight", "ocean", "light", "amber"})
ALLOWED_SLEEP_VIEWS = frozenset({"logo", "logo_time", "logo_time_date"})
ALLOWED_SLEEP_EFFECTS = frozenset({"off", "soft_glow", "pulse_glow", "aurora", "liquid_motion"})
#: Schoolplatformen die de setup-app mag aanbieden. Alleen "mock" heeft een
#: werkende adapter; de rest is voorbereid maar "nog niet beschikbaar".
ALLOWED_PROVIDERS = frozenset({"mock", "magister", "somtoday", "osiris", "myx"})
#: Standaardtijdzone van de wekker (Nederland). DST wordt automatisch door
#: zoneinfo afgehandeld; er wordt nergens een vaste UTC-offset gehanteerd.
DEFAULT_TIMEZONE = "Europe/Amsterdam"
#: Standaardregio (ISO 3166-1 alpha-2).
DEFAULT_REGION = "NL"
ALLOWED_TIME_FORMATS = frozenset({"24h", "12h"})


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
class AlarmProfile:
    """Eén zelfstandig dagelijks alarm.

    ``id`` blijft stabiel zodat meerdere alarmen dezelfde dag onafhankelijk
    kunnen worden geactiveerd, gesnoozed en afgevinkt.
    """

    id: str = "alarm-1"
    time: str = "07:30"
    enabled: bool = True
    snooze_minutes: int = 9
    sound: str = "beep"
    volume: int = 70
    speaker_enabled: bool = True
    lamp_brightness: int = 100
    lamp_blink: bool = True
    blink_pattern: str = "blink"
    ramp_up_seconds: int = 30

    def __post_init__(self) -> None:
        self.id = str(self.id or "").strip()
        if not self.id or len(self.id) > 64:
            raise SettingsError("alarm-id moet 1–64 tekens lang zijn")
        self.time = _check_time(self.time, "alarm.time")
        self.enabled = _check_bool(self.enabled, "alarm.enabled")
        self.snooze_minutes = _check_range(
            self.snooze_minutes, "alarm.snooze_minutes", 1, 60
        )
        self.volume = _check_range(self.volume, "alarm.volume", 0, 100)
        self.speaker_enabled = _check_bool(
            self.speaker_enabled, "alarm.speaker_enabled"
        )
        self.lamp_brightness = _check_range(
            self.lamp_brightness, "alarm.lamp_brightness", 0, 100
        )
        self.lamp_blink = _check_bool(self.lamp_blink, "alarm.lamp_blink")
        if self.blink_pattern not in ALLOWED_BLINK_PATTERNS:
            raise SettingsError(
                f"alarm.blink_pattern onbekend: {self.blink_pattern!r}"
            )
        self.ramp_up_seconds = _check_range(
            self.ramp_up_seconds, "alarm.ramp_up_seconds", 0, 3600
        )
        if not self.sound or not isinstance(self.sound, str):
            raise SettingsError("alarm.sound moet een niet-lege naam zijn")


@dataclass
class AlarmSettings:
    """Alarmconfiguratie met backwards compatibility voor v9 en ouder.

    De oude velden blijven bestaan voor cloud/webcompatibiliteit. ``alarms`` is
    in v10 de bron van waarheid. Bij oude instellingen wordt automatisch één
    profiel aangemaakt; de legacyvelden spiegelen altijd het eerste profiel.
    """

    time: str = "07:30"
    enabled: bool = True
    snooze_minutes: int = 9
    sound: str = "beep"
    volume: int = 70
    speaker_enabled: bool = True
    lamp_brightness: int = 100
    lamp_blink: bool = True
    blink_pattern: str = "blink"
    ramp_up_seconds: int = 30
    alarms: list[AlarmProfile | dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Valideer eerst de legacy/defaultwaarden zodat oude JSON geldig blijft.
        legacy = AlarmProfile(
            id="alarm-1",
            time=self.time,
            enabled=self.enabled,
            snooze_minutes=self.snooze_minutes,
            sound=self.sound,
            volume=self.volume,
            speaker_enabled=self.speaker_enabled,
            lamp_brightness=self.lamp_brightness,
            lamp_blink=self.lamp_blink,
            blink_pattern=self.blink_pattern,
            ramp_up_seconds=self.ramp_up_seconds,
        )

        normalized: list[AlarmProfile] = []
        for raw in self.alarms:
            if isinstance(raw, AlarmProfile):
                profile = raw
            elif isinstance(raw, dict):
                try:
                    profile = AlarmProfile(**raw)
                except TypeError as exc:
                    raise SettingsError(f"Onbekende alarmprofielsleutel: {exc}") from exc
            else:
                raise SettingsError("alarm.alarms moet een lijst met alarmobjecten zijn")
            normalized.append(profile)

        if not normalized:
            normalized = [legacy]
        if len(normalized) > 12:
            raise SettingsError("Maximaal 12 alarmen zijn toegestaan")

        ids = [p.id for p in normalized]
        if len(set(ids)) != len(ids):
            raise SettingsError("Alarm-id's moeten uniek zijn")

        # Stabiele tijdvolgorde in opslag/UI.
        normalized.sort(key=lambda p: (p.time, p.id))
        self.alarms = normalized
        self._mirror_primary()

    def _mirror_primary(self) -> None:
        primary = self.alarms[0]
        self.time = primary.time
        self.enabled = primary.enabled
        self.snooze_minutes = primary.snooze_minutes
        self.sound = primary.sound
        self.volume = primary.volume
        self.speaker_enabled = primary.speaker_enabled
        self.lamp_brightness = primary.lamp_brightness
        self.lamp_blink = primary.lamp_blink
        self.blink_pattern = primary.blink_pattern
        self.ramp_up_seconds = primary.ramp_up_seconds

    def get(self, alarm_id: str) -> AlarmProfile | None:
        for profile in self.alarms:
            if profile.id == alarm_id:
                return profile
        return None


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
    theme: str = "midnight"
    on_duration_seconds: int = 30
    # Slaapmodus is een donkere screensaver; 0 betekent "nooit".
    sleep_after_seconds: int = 60
    sleep_view: str = "logo_time_date"
    sleep_effect: str = "soft_glow"
    sleep_glow_intensity: int = 65
    night_mode: str = "dim"
    night_start: str = "23:00"
    night_end: str = "07:00"
    visible_fields: list[str] = field(
        default_factory=lambda: ["time", "next_alarm", "first_lesson", "teacher", "room"]
    )

    def __post_init__(self) -> None:
        self.brightness = _check_range(self.brightness, "display.brightness", 0, 100)
        if self.theme not in ALLOWED_THEMES:
            raise SettingsError(
                f"display.theme onbekend: {self.theme!r} "
                f"(kies uit {sorted(ALLOWED_THEMES)})"
            )
        self.on_duration_seconds = _check_range(
            self.on_duration_seconds, "display.on_duration_seconds", 1, 600
        )
        self.sleep_after_seconds = _check_range(
            self.sleep_after_seconds, "display.sleep_after_seconds", 0, 3600
        )
        if self.sleep_view not in ALLOWED_SLEEP_VIEWS:
            raise SettingsError(
                f"display.sleep_view onbekend: {self.sleep_view!r} "
                f"(kies uit {sorted(ALLOWED_SLEEP_VIEWS)})"
            )
        if self.sleep_effect not in ALLOWED_SLEEP_EFFECTS:
            raise SettingsError(
                f"display.sleep_effect onbekend: {self.sleep_effect!r} "
                f"(kies uit {sorted(ALLOWED_SLEEP_EFFECTS)})"
            )
        self.sleep_glow_intensity = _check_range(
            self.sleep_glow_intensity, "display.sleep_glow_intensity", 0, 100
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
    time_format: str = "24h"

    def __post_init__(self) -> None:
        self.timezone = _check_timezone(self.timezone)
        self.region = _check_region(self.region)
        if self.time_format not in ALLOWED_TIME_FORMATS:
            raise SettingsError(
                f"locale.time_format onbekend: {self.time_format!r} "
                f"(kies uit {sorted(ALLOWED_TIME_FORMATS)})"
            )


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
        """Valideer een gedeeltelijke update; atomic: bij fout verandert niets.

        v10 bewaart meerdere alarmen in ``alarm.alarms``. Oude cloud/webclients
        die alleen ``alarm.time`` of ``alarm.volume`` wijzigen blijven werken:
        zo'n wijziging wordt ook op het eerste alarmprofiel toegepast.
        """
        huidig = self.to_dict()
        legacy_alarm_keys = {
            "time", "enabled", "snooze_minutes", "sound", "volume",
            "speaker_enabled", "lamp_brightness", "lamp_blink",
            "blink_pattern", "ramp_up_seconds",
        }
        for sectie, waarden in patch.items():
            if sectie not in huidig:
                raise SettingsError(f"Onbekende sectie: {sectie!r}")
            if not isinstance(waarden, dict):
                raise SettingsError(f"Sectie {sectie!r} moet een object zijn")
            for sleutel in waarden:
                if sleutel not in huidig[sectie]:
                    raise SettingsError(f"Onbekende sleutel: {sectie}.{sleutel}")

            waarden = dict(waarden)
            if sectie == "alarm" and "alarms" not in waarden:
                alarms = [dict(x) for x in huidig["alarm"].get("alarms", [])]
                if alarms:
                    for key, value in waarden.items():
                        if key in legacy_alarm_keys:
                            alarms[0][key] = value
                    waarden["alarms"] = alarms

            merged = {**huidig[sectie], **waarden}
            huidig[sectie] = merged
        return Settings.from_dict(huidig)


def default_settings() -> Settings:
    return Settings()
