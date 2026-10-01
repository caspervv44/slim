"""MyX/Xedule agenda-provider via de InternetCalendar (ICS) API.

Authenticatie komt uitsluitend uit environment variables. De Bearer-token wordt
nooit opgeslagen in Settings, de webinterface of logs.
"""

from __future__ import annotations

import os
import re
import html
from urllib.parse import unquote
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from wekker.agenda.models import Lesson
from wekker.agenda.providers import ProviderError

ENV_MYX_BEARER_TOKEN = "WEKKER_MYX_BEARER_TOKEN"
ENV_MYX_ATT_ID = "WEKKER_MYX_ATT_ID"
ENV_MYX_CALENDAR_URL = "WEKKER_MYX_CALENDAR_URL"

DEFAULT_MYX_CALENDAR_URL = "https://aventus.myx.nl/api/InternetCalendar"
REQUIRED_MYX_ENV = (ENV_MYX_BEARER_TOKEN, ENV_MYX_ATT_ID)

# De MyX-export gebruikt een Windows-tijdzonenaam in plaats van IANA.
WINDOWS_TZ_TO_IANA = {
    "W. Europe Standard Time": "Europe/Amsterdam",
    "Romance Standard Time": "Europe/Paris",
}

LOCAL_TZ = ZoneInfo("Europe/Amsterdam")
DEFAULT_SYNC_HORIZON_DAYS = 21
DEFAULT_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class MyXConfig:
    bearer_token: str = ""
    att_id: str = ""
    calendar_url: str = DEFAULT_MYX_CALENDAR_URL
    # Een MyX-feed is een stabiele iCalendar-abonnement-URL. Als die is
    # ingesteld is er voor dagelijkse synchronisatie geen Bearer-token nodig.
    feed_url: str = ""

    @classmethod
    def from_env(cls) -> "MyXConfig":
        return cls(
            bearer_token=os.getenv(ENV_MYX_BEARER_TOKEN, "").strip(),
            att_id=os.getenv(ENV_MYX_ATT_ID, "").strip(),
            calendar_url=os.getenv(ENV_MYX_CALENDAR_URL, DEFAULT_MYX_CALENDAR_URL).strip()
            or DEFAULT_MYX_CALENDAR_URL,
        )

    @property
    def configured(self) -> bool:
        return bool(self.feed_url or (self.bearer_token and self.att_id))

    def missing(self) -> list[str]:
        if self.feed_url:
            return []
        ontbrekend = []
        if not self.bearer_token:
            ontbrekend.append(ENV_MYX_BEARER_TOKEN)
        if not self.att_id:
            ontbrekend.append(ENV_MYX_ATT_ID)
        return ontbrekend


def _unfold_ics(text: str) -> list[str]:
    """Vouw RFC 5545 continuation lines terug tot logische regels."""
    fysieke_regels = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    regels: list[str] = []
    for regel in fysieke_regels:
        if regel.startswith((" ", "\t")):
            if not regels:
                raise ProviderError("Ongeldige ICS: continuation zonder vorige regel")
            regels[-1] += regel[1:]
        else:
            regels.append(regel)
    return regels


def _split_property(line: str) -> tuple[str, dict[str, str], str]:
    if ":" not in line:
        raise ProviderError("Ongeldige ICS-regel zonder ':'")
    left, value = line.split(":", 1)
    delen = left.split(";")
    naam = delen[0].upper()
    params: dict[str, str] = {}
    for deel in delen[1:]:
        if "=" in deel:
            sleutel, waarde = deel.split("=", 1)
            params[sleutel.upper()] = waarde.strip('"')
    return naam, params, value


def _unescape_text(value: str) -> str:
    """Decodeer de tekst-escaping uit RFC 5545."""
    # Eerst newline-sequenties, daarna escaped leestekens/backslash.
    value = re.sub(r"\\[nN]", "\n", value)
    value = value.replace(r"\,", ",").replace(r"\;", ";")
    value = value.replace(r"\\", "\\")
    return value.strip()


def _parse_datetime(value: str, params: dict[str, str]) -> datetime | None:
    """Parse een ICS-datum/tijd naar Europe/Amsterdam.

    VALUE=DATE (hele-dag-item) retourneert None: het bestaande Lesson-model is
    bewust een tijdgebonden les binnen één kalenderdag.
    """
    if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", value):
        return None

    is_utc = value.endswith("Z")
    raw = value[:-1] if is_utc else value
    formaat = "%Y%m%dT%H%M%S" if len(raw) == 15 else "%Y%m%dT%H%M"
    try:
        dt = datetime.strptime(raw, formaat)
    except ValueError as exc:
        raise ProviderError(f"Ongeldige ICS-datum/tijd: {value!r}") from exc

    if is_utc:
        return dt.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)

    tzid = params.get("TZID")
    if tzid:
        iana = WINDOWS_TZ_TO_IANA.get(tzid, tzid)
        try:
            zone = ZoneInfo(iana)
        except ZoneInfoNotFoundError as exc:
            raise ProviderError(f"Onbekende ICS-tijdzone: {tzid!r}") from exc
    else:
        # RFC 5545 floating time: voor deze wekker interpreteren we die in de
        # ingestelde schoolzone. MyX gebruikt normaliter expliciet TZID.
        zone = LOCAL_TZ
    return dt.replace(tzinfo=zone).astimezone(LOCAL_TZ)


def _extract_labeled(description: str, labels: tuple[str, ...]) -> str:
    """Lees een gelabelde waarde uit vrije tekst of HTML-resttekst.

    MyX/Xedule kan labels als ``Lokaal:``, ``Locatie(s):`` of ``Room -``
    gebruiken. We accepteren daarom ``:`` en ``-`` als scheiding en negeren
    een optioneel ``(s)``-suffix.
    """
    wanted = {re.sub(r"[^a-z0-9]", "", label.casefold()) for label in labels}
    for regel in str(description or "").splitlines():
        match = re.match(r"^\s*([^:=–—-]{2,40}?)\s*(?::|=|\s[-–—]\s)\s*(.+?)\s*$", regel)
        if not match:
            continue
        key = re.sub(r"[^a-z0-9]", "", match.group(1).casefold())
        if key in wanted:
            return match.group(2).strip()
    return ""


def _clean_room_value(value: str) -> str:
    """Normaliseer lege/placeholder-locaties uit MyX/Xedule."""
    value = html.unescape(str(value or ""))
    # Sommige vendorvelden bevatten URL-encoded tekst.
    try:
        value = unquote(value)
    except Exception:
        pass
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"</(?:div|p|li|tr|td)>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("\\n", "\n")
    value = re.sub(r"[\t\r ]+", " ", value)
    value = re.sub(r"\n\s*", "\n", value).strip(" \t\r\n,;")
    compact = re.sub(r"[\s._/\\-]+", "", value).casefold()
    if compact in {
        "", "nvt", "geen", "geenlokaal", "geenlocatie", "onbekend",
        "tbd", "na", "none", "null",
    }:
        return ""
    # Losse streepjes en vergelijkbare placeholders.
    if re.fullmatch(r"[-–—_.?/\\ ]+", value):
        return ""
    return value


def _extract_room_candidates(text: str) -> str:
    """Zoek waarschijnlijke lokaalcodes in vrije MyX/Xedule-tekst.

    Ondersteunt onder andere ``LVM-E2.12``, ``LVM E2.12``, ``E2.14``,
    ``B1-03`` en optionele letters achter het lokaalnummer. Resultaten blijven
    bewust conservatief zodat groepscodes en tijden niet als lokaal eindigen.
    """
    text = _clean_room_value(text)
    if not text:
        return ""

    found: list[str] = []
    # Campusprefix + lokaalcode. Voorbeeld: LVM-E2.12, LVM E2.12A, E2-14.
    pattern = re.compile(
        r"\b(?:(?P<prefix>[A-Z]{2,10})[\s_-]+)?"
        r"(?P<room>[A-Z]{1,3}\d{1,2}(?:[.-]\d{1,3})+[A-Z]?)\b",
        re.I,
    )
    for match in pattern.finditer(text.upper()):
        prefix = (match.group("prefix") or "").strip()
        room = match.group("room").strip().replace("-", ".")
        candidate = f"{prefix}-{room}" if prefix else room
        if candidate not in found:
            found.append(candidate)

    # Als een expliciet lokaal-/roomlabel aanwezig is, accepteren we ook een
    # numerieke kamercode zoals ``2.12``. Zonder label zou dat te snel een
    # datum/versie kunnen zijn.
    labeled_numeric = re.compile(
        r"(?i)\b(?:lokaal(?:\(s\)|en)?|locatie(?:\(s\)|s)?|"
        r"room(?:\(s\)|s)?|ruimte(?:\(s\)|s)?)\s*[:=-]\s*"
        r"(?P<value>\d{1,2}[.-]\d{1,3}[A-Z]?)\b"
    )
    for match in labeled_numeric.finditer(text):
        candidate = match.group("value").upper().replace("-", ".")
        if candidate not in found:
            found.append(candidate)

    return " / ".join(found[:4])


def _extract_event_room(
    event: dict[str, list[tuple[dict[str, str], str]]],
    description: str,
    location: str,
) -> str:
    """Vind een lokaal uitsluitend wanneer de iCal-data er echt één bevat.

    Xedule kan het lokaal in ``LOCATION``, ``DESCRIPTION``, ``RESOURCES``,
    vendorvelden of in propertyparameters zoals ``ATTENDEE;CN=...`` zetten.
    Een placeholder zoals ``-`` telt nooit als lokaal. Als er nergens bruikbare
    locatie-informatie staat, geven we een lege string terug zodat de GUI het
    lokaalblok volledig verbergt in plaats van ``Lokaal: -`` te tonen.
    """
    clean_location = _clean_room_value(location)
    location_candidates = _extract_room_candidates(clean_location)
    if location_candidates:
        return location_candidates

    labels = (
        "Lokaal", "Lokalen", "Lokaal(s)",
        "Locatie", "Locaties", "Locatie(s)",
        "Location", "Locations",
        "Room", "Rooms", "Room(s)",
        "Ruimte", "Ruimtes", "Ruimte(s)",
    )
    labeled = _clean_room_value(_extract_labeled(description, labels))
    labeled_candidates = _extract_room_candidates(labeled)
    if labeled_candidates:
        return labeled_candidates
    # Een expliciet gelabelde niet-placeholder locatie mag ook gewone tekst zijn.
    if labeled and len(labeled) <= 80:
        return labeled

    candidates = _extract_room_candidates(description)
    if candidates:
        return candidates

    # Eerst velden die semantisch het meest waarschijnlijk een ruimte bevatten.
    preferred_names = (
        "RESOURCES", "X-ROOM", "X-ROOMS", "X-LOCATION",
        "X-APPLE-STRUCTURED-LOCATION", "X-MICROSOFT-CDO-LOCATION",
        "X-ALT-DESC", "COMMENT", "ATTENDEE",
    )
    ordered_names = list(preferred_names) + [
        name for name in event.keys() if name not in preferred_names
    ]
    skip = {"DTSTART", "DTEND", "DTSTAMP", "UID", "CREATED", "LAST-MODIFIED"}

    searchable: list[str] = []
    for name in ordered_names:
        if name in skip:
            continue
        for params, value in event.get(name, []):
            # Kamers worden in sommige exporters als ATTENDEE/RESOURCE met
            # CN-parameter geschreven, bv. ATTENDEE;CUTYPE=ROOM;CN=LVM-E2.12.
            param_text = " ".join(
                f"{key}={param_value}" for key, param_value in params.items()
            )
            try:
                decoded = _unescape_text(value)
            except Exception:
                decoded = value
            searchable.extend((name, param_text, decoded))

            if (
                name in {"ATTENDEE", "RESOURCES"}
                or str(params.get("CUTYPE", "")).casefold() in {"room", "resource"}
                or str(params.get("ROLE", "")).casefold() == "room"
            ):
                candidates = _extract_room_candidates(f"{param_text} {decoded}")
                if candidates:
                    return candidates

    candidates = _extract_room_candidates("\n".join(searchable))
    if candidates:
        return candidates

    # Alleen een echte, betekenisvolle LOCATION als fallback gebruiken. Een
    # algemene campusnaam (zoals LVM) mag getoond worden, maar nooit een dash.
    return clean_location


def parse_ics(text: str) -> list[Lesson]:
    """Vertaal een MyX iCalendar-response naar generieke Lesson-objecten."""
    if not isinstance(text, str) or not text.strip():
        raise ProviderError("Lege ICS-response")

    regels = _unfold_ics(text)
    if not any(r.strip().upper() == "BEGIN:VCALENDAR" for r in regels):
        raise ProviderError("Ongeldige ICS: BEGIN:VCALENDAR ontbreekt")
    if not any(r.strip().upper() == "END:VCALENDAR" for r in regels):
        raise ProviderError("Ongeldige ICS: END:VCALENDAR ontbreekt")

    events: list[dict[str, list[tuple[dict[str, str], str]]]] = []
    huidig: dict[str, list[tuple[dict[str, str], str]]] | None = None

    for raw in regels:
        line = raw.strip("\ufeff")
        upper = line.upper()
        if upper == "BEGIN:VEVENT":
            if huidig is not None:
                raise ProviderError("Ongeldige ICS: geneste VEVENT")
            huidig = {}
            continue
        if upper == "END:VEVENT":
            if huidig is None:
                raise ProviderError("Ongeldige ICS: END:VEVENT zonder BEGIN")
            events.append(huidig)
            huidig = None
            continue
        if huidig is None or not line:
            continue

        naam, params, value = _split_property(line)
        huidig.setdefault(naam, []).append((params, value))

    if huidig is not None:
        raise ProviderError("Ongeldige ICS: VEVENT niet afgesloten")

    lessen: list[Lesson] = []
    for event in events:
        try:
            summary_raw = event["SUMMARY"][0][1]
            start_params, start_raw = event["DTSTART"][0]
            end_params, end_raw = event["DTEND"][0]
        except (KeyError, IndexError) as exc:
            raise ProviderError("Ongeldige ICS: VEVENT mist SUMMARY/DTSTART/DTEND") from exc

        start = _parse_datetime(start_raw, start_params)
        end = _parse_datetime(end_raw, end_params)
        # Hele-dag-items (bijv. vakantiedagen) passen niet in Lesson en worden
        # daarom bewust niet als les gepresenteerd.
        if start is None or end is None:
            continue

        subject = _unescape_text(summary_raw)
        description = _unescape_text(event.get("DESCRIPTION", [({}, "")])[0][1])
        location = _unescape_text(event.get("LOCATION", [({}, "")])[0][1])
        location = _extract_event_room(event, description, location)
        teacher = _extract_labeled(description, ("Docent", "Teacher", "Begeleider"))

        try:
            lessen.append(
                Lesson(
                    subject=subject,
                    start=start,
                    end=end,
                    teacher=teacher,
                    room=location,
                    source="myx",
                )
            )
        except ValueError as exc:
            raise ProviderError(f"Ongeldige MyX-afspraak {subject!r}: {exc}") from exc

    return sorted(lessen, key=lambda les: les.start)


def inspect_ics_room_hints(text: str) -> dict[str, object]:
    """Geef een privacyvriendelijke samenvatting van lokaalinformatie in ICS.

    De functie toont geen feed-URL, volledige beschrijvingen, vaknamen of
    deelnemers. Alleen propertynamen, aantallen en lokaalachtige codes worden
    teruggegeven. Zo kan op de Raspberry Pi worden vastgesteld of de bronfeed
    überhaupt lokaalinformatie bevat als de GUI niets toont.
    """
    if not isinstance(text, str) or not text.strip():
        raise ProviderError("Lege ICS-response")

    interesting_names = {
        "LOCATION", "RESOURCES", "X-ROOM", "X-ROOMS", "X-LOCATION",
        "X-APPLE-STRUCTURED-LOCATION", "X-MICROSOFT-CDO-LOCATION",
        "X-ALT-DESC", "COMMENT", "DESCRIPTION", "ATTENDEE",
    }
    property_counts: dict[str, int] = {}
    room_candidates: list[str] = []
    events = 0
    in_event = False

    for raw in _unfold_ics(text):
        line = raw.strip("\ufeff")
        upper = line.upper()
        if upper == "BEGIN:VEVENT":
            events += 1
            in_event = True
            continue
        if upper == "END:VEVENT":
            in_event = False
            continue
        if not in_event or not line or ":" not in line:
            continue
        try:
            name, params, value = _split_property(line)
        except ProviderError:
            continue

        decoded = _unescape_text(value)
        param_text = " ".join(f"{k}={v}" for k, v in params.items())

        nonempty_location = name == "LOCATION" and bool(_clean_room_value(decoded))
        is_room_resource = (
            name in {"ATTENDEE", "RESOURCES"}
            and (
                str(params.get("CUTYPE", "")).casefold() in {"room", "resource"}
                or "room" in param_text.casefold()
            )
        )
        candidate = _extract_room_candidates(f"{param_text} {decoded}")

        if name in interesting_names and (candidate or nonempty_location or is_room_resource):
            property_counts[name] = property_counts.get(name, 0) + 1

        if candidate:
            for item in (part.strip() for part in candidate.split("/")):
                if item and item not in room_candidates:
                    room_candidates.append(item)

    return {
        "events": events,
        "room_property_counts": dict(sorted(property_counts.items())),
        "room_candidates": room_candidates[:20],
        "source_has_room_hints": bool(property_counts or room_candidates),
    }


class MyXAgendaProvider:
    """MyX/Xedule-adapter.

    ``fetch_range`` haalt een periode in één HTTP-request op. De syncservice
    gebruikt deze methode voor de standaard horizon van drie weken.
    """

    name = "myx"
    sync_horizon_days = DEFAULT_SYNC_HORIZON_DAYS

    def __init__(
        self,
        config: MyXConfig | None = None,
        *,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        opener=None,
        config_loader=None,
    ) -> None:
        self.config = config or MyXConfig.from_env()
        self.timeout_seconds = timeout_seconds
        self._opener = opener or urllib.request.urlopen
        self._config_loader = config_loader

    def _current_config(self) -> MyXConfig:
        """Lees credentials zo laat mogelijk zodat vernieuwde tokens direct gelden."""
        if self._config_loader is None:
            return self.config
        try:
            config = self._config_loader()
        except Exception as exc:
            # Import hier om een harde circulaire dependency te vermijden.
            from wekker.agenda.myx_auth import MyXAuthError

            if isinstance(exc, MyXAuthError):
                raise ProviderError(str(exc)) from exc
            raise
        if not isinstance(config, MyXConfig):
            raise ProviderError("MyX credential-loader gaf ongeldige configuratie.")
        return config

    def _require_config(self) -> MyXConfig:
        config = self._current_config()
        if not config.configured:
            namen = ", ".join(config.missing())
            raise ProviderError(
                "MyX is niet geconfigureerd; ontbrekende environment variables: "
                f"{namen}"
            )
        return config

    def fetch_raw_ics(self, start: date, end_exclusive: date) -> str:
        """Download de ruwe ICS voor diagnose zonder de feed-URL te loggen."""
        config = self._require_config()
        if end_exclusive <= start:
            raise ProviderError("MyX-datumbereik moet minimaal één dag bevatten")

        if config.feed_url:
            # De Feed-knop in MyX maakt een webcal-abonnement. Het bijbehorende
            # HTTPS-adres is stabiel en bedoeld om periodiek door agenda-apps
            # te worden opgehaald. Het bevat geen datumparameter.
            url = config.feed_url
            headers = {
                "Accept": "text/calendar, text/plain;q=0.9, */*;q=0.1",
                "User-Agent": "WakeSync/10.0.0",
            }
        else:
            query = urllib.parse.urlencode(
                {
                    "start": start.isoformat(),
                    "end": end_exclusive.isoformat(),
                    "attId": config.att_id,
                }
            )
            url = f"{config.calendar_url}?{query}"
            headers = {
                "Authorization": f"Bearer {config.bearer_token}",
                "Accept": "text/calendar, text/plain;q=0.9, */*;q=0.1",
                "User-Agent": "WakeSync/10.0.0",
            }

        request = urllib.request.Request(url, headers=headers, method="GET")

        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                payload = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                if config.feed_url:
                    raise ProviderError(
                        "De MyX-feed is niet meer geldig; koppel de feed opnieuw via de webinstellingen."
                    ) from exc
                raise ProviderError(
                    "MyX-authenticatie geweigerd; log opnieuw in of gebruik de MyX-feed."
                ) from exc
            raise ProviderError(f"MyX API gaf HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"MyX API niet bereikbaar: {type(exc).__name__}") from exc

        try:
            return payload.decode(charset)
        except (LookupError, UnicodeDecodeError) as exc:
            raise ProviderError("MyX ICS-response heeft ongeldige tekstcodering") from exc

    def fetch_range(self, start: date, end_exclusive: date) -> list[Lesson]:
        """Haal ``start <= dag < end_exclusive`` op via InternetCalendar."""
        text = self.fetch_raw_ics(start, end_exclusive)
        lessen = parse_ics(text)
        # Sommige calendar-servers behandelen 'end' inclusief. Filter daarom
        # altijd zelf op het gevraagde half-open bereik.
        return [les for les in lessen if start <= les.start.date() < end_exclusive]

    def fetch_day(self, day: date) -> list[Lesson]:
        return [
            les
            for les in self.fetch_range(day, day + timedelta(days=1))
            if les.start.date() == day
        ]
