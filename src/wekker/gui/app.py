"""WakeSync v9 fullscreen touchscreen-app voor 800×480 Raspberry Pi.

De renderer blijft bewust Tkinter. Netwerk- en hardwaredetectietaken lopen op
achtergrondthreads; widgets worden alleen op de Tk-hoofdthread gewijzigd.
"""

from __future__ import annotations

from datetime import date, timedelta
import math
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any

from wekker.gui.screens import (
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    DUTCH_MONTHS,
    DUTCH_WEEKDAYS,
    AlarmScreenData,
    GuiData,
    Navigator,
    ScreenId,
    SettingsScreenData,
    build_agenda_data,
    build_main_data,
    format_day_label,
    format_time,
    layout_for,
)

log = logging.getLogger(__name__)
REFRESH_MS = 1000

THEMES = {
    "midnight": {
        "bg": "#08111f", "card": "#101c2e", "card_alt": "#132239",
        "text": "#f8fafc", "muted": "#8ea2bd", "accent": "#4f8cff",
        "accent_dark": "#2f63bd", "border": "#1e3049", "success": "#55d6a3",
        "danger": "#ef6b73",
    },
    "ocean": {
        "bg": "#071a22", "card": "#0d2933", "card_alt": "#123743",
        "text": "#eefcff", "muted": "#91bac4", "accent": "#42c7e8",
        "accent_dark": "#1689a6", "border": "#1b4855", "success": "#5de0af",
        "danger": "#ff7b86",
    },
    "light": {
        "bg": "#edf3f8", "card": "#ffffff", "card_alt": "#e4edf5",
        "text": "#172033", "muted": "#617286", "accent": "#2563eb",
        "accent_dark": "#cfe0ff", "border": "#cbd7e3", "success": "#17795a",
        "danger": "#b42318",
    },
    "amber": {
        "bg": "#160f08", "card": "#251a0e", "card_alt": "#342416",
        "text": "#fff7e8", "muted": "#c5a77f", "accent": "#ffb020",
        "accent_dark": "#9a5a00", "border": "#4d361f", "success": "#64d8a4",
        "danger": "#ff7777",
    },
}
THEME_CHOICES = (
    ("midnight", "Midnight"),
    ("ocean", "Ocean"),
    ("light", "Light"),
    ("amber", "Amber"),
)
SLEEP_AFTER_CHOICES = (
    (0, "Nooit"),
    (30, "30 seconden"),
    (60, "1 minuut"),
    (300, "5 minuten"),
    (900, "15 minuten"),
)
SLEEP_VIEW_CHOICES = (
    ("logo", "Alleen logo"),
    ("logo_time", "Logo + tijd"),
    ("logo_time_date", "Logo + tijd + datum"),
)
SLEEP_EFFECT_CHOICES = (
    ("off", "Geen effect"),
    ("soft_glow", "Zachte gloed"),
    ("pulse_glow", "Pulserende gloed"),
    ("aurora", "Aurora"),
)
SLEEP_GLOW_LEVELS = (0, 25, 50, 65, 75, 100)
TIMEZONE_CHOICES = (
    ("Europe/Amsterdam", "Amsterdam · CET/CEST"),
    ("Europe/Brussels", "Brussel · CET/CEST"),
    ("Europe/Berlin", "Berlijn · CET/CEST"),
    ("Europe/Paris", "Parijs · CET/CEST"),
    ("Europe/London", "Londen · GMT/BST"),
    ("Europe/Madrid", "Madrid · CET/CEST"),
    ("Europe/Rome", "Rome · CET/CEST"),
    ("UTC", "UTC"),
)


def _set_theme_palette(theme: str) -> None:
    global BG, CARD, CARD_ALT, TEXT, MUTED, ACCENT, ACCENT_DARK, BORDER, SUCCESS, DANGER
    palette = THEMES.get(theme, THEMES["midnight"])
    BG = palette["bg"]
    CARD = palette["card"]
    CARD_ALT = palette["card_alt"]
    TEXT = palette["text"]
    MUTED = palette["muted"]
    ACCENT = palette["accent"]
    ACCENT_DARK = palette["accent_dark"]
    BORDER = palette["border"]
    SUCCESS = palette["success"]
    DANGER = palette["danger"]


_set_theme_palette("midnight")


def build_gui_data(
    runtime: Any,
    agenda_day: date | None = None,
    agenda_page: int = 0,
) -> GuiData:
    """Maak één consistente schermsnapshot uit de runtime."""
    from wekker.agenda.providers import get_provider_info

    ctx = runtime.ctx
    now = ctx.clock.now()
    agenda_day = agenda_day or now.date()
    try:
        provider_name = get_provider_info(ctx.settings.agenda.provider).display_name
    except ValueError:
        provider_name = ctx.settings.agenda.provider

    cache = ctx.cache
    today_loaded = bool(getattr(cache, "is_day_loaded", lambda _d: True)(now.date()))
    selected_loaded = bool(getattr(cache, "is_day_loaded", lambda _d: True)(agenda_day))
    agenda_status = (
        cache.display_status(now)
        if hasattr(cache, "display_status")
        else ("Bijgewerkt" if getattr(cache, "last_sync", None) else "Nog niet geladen")
    )
    notice = str(getattr(ctx.core, "missed_notice", "") or "")

    return GuiData(
        main=build_main_data(
            now,
            ctx.core.next_alarm(now),
            time_format=ctx.settings.locale.time_format,
            lessons=cache.get_day(now.date()),
            agenda_loaded=today_loaded,
            agenda_status=agenda_status,
            notice=notice,
        ),
        agenda=build_agenda_data(
            cache.get_day(agenda_day),
            provider_name=provider_name,
            day_label=format_day_label(agenda_day, now.date()),
            page=agenda_page,
            now=now,
            loaded=selected_loaded,
            status_text=agenda_status,
        ),
        alarm=AlarmScreenData(
            time=ctx.settings.alarm.time,
            enabled=ctx.settings.alarm.enabled,
            snooze_minutes=ctx.settings.alarm.snooze_minutes,
            sound=ctx.settings.alarm.sound,
            volume=ctx.settings.alarm.volume,
            speaker_enabled=ctx.settings.alarm.speaker_enabled,
            lamp_brightness=ctx.settings.alarm.lamp_brightness,
            lamp_blink=ctx.settings.alarm.lamp_blink,
            blink_pattern=ctx.settings.alarm.blink_pattern,
            ramp_up_seconds=ctx.settings.alarm.ramp_up_seconds,
        ),
        settings=SettingsScreenData(
            timezone=ctx.settings.locale.timezone,
            time_format=ctx.settings.locale.time_format,
            region=ctx.settings.locale.region,
            theme=ctx.settings.display.theme,
            sleep_after_seconds=ctx.settings.display.sleep_after_seconds,
            sleep_view=ctx.settings.display.sleep_view,
            sleep_effect=ctx.settings.display.sleep_effect,
            sleep_glow_intensity=ctx.settings.display.sleep_glow_intensity,
            provider=ctx.settings.agenda.provider,
            **_cloud_screen_kwargs(ctx),
        ),
    )


def _cloud_screen_kwargs(ctx: Any) -> dict[str, Any]:
    cloud = getattr(ctx, "cloud", None)
    if cloud is None:
        return {}
    try:
        info = cloud.display_info()
    except Exception:
        return {"cloud_status": "Cloudkoppeling niet beschikbaar"}
    return {
        "cloud_ready": info.ready,
        "cloud_url": info.management_url,
        "cloud_username": info.username,
        "cloud_password": info.initial_password,
        "cloud_password_changed": info.password_changed,
        "cloud_status": info.status,
        "cloud_error": info.error,
        "cloud_revision": info.revision,
        "cloud_last_sync": info.last_sync_at,
    }


def _short(text: str, limit: int) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[: max(1, limit - 1)].rstrip() + "…"


class TouchApp:
    def __init__(self, root: Any, runtime: Any, navigator: Navigator | None = None) -> None:
        self._root = root
        self._runtime = runtime
        self._nav = navigator or Navigator()
        self._running = True
        self._agenda_day: date | None = None
        self._agenda_page = 0
        self._last_today: date | None = None
        self._settings_overlay: Any | None = None
        self._settings_section: str | None = None
        self._qr_overlay: Any | None = None
        self._sleep_overlay: Any | None = None
        self._sleeping = False
        self._alarm_overlay: Any | None = None
        self._update_overlay: Any | None = None
        self._update_info: Any | None = None
        self._toast: Any | None = None
        self._last_activity = time.monotonic()
        self._sleep_animation_job: str | None = None
        self._sleep_phase = 0.0
        self._alarm_picker_mode = "hour"

        try:
            self._active_theme = str(runtime.ctx.settings.display.theme)
        except Exception:
            self._active_theme = "midnight"
        _set_theme_palette(self._active_theme)

        root.title("WakeSync")
        try:
            root.geometry(f"{SCREEN_WIDTH}x{SCREEN_HEIGHT}")
        except Exception:
            pass

        self._frame = self._make_frame()
        self._screen: str | None = None
        self._widgets: dict[str, Any] = {}

        try:
            root.bind_all("<ButtonPress-1>", self._on_user_activity, add="+")
            root.bind_all("<KeyPress>", self._on_user_activity, add="+")
        except Exception:
            pass

        self.render()

    def _tk(self) -> Any:
        import tkinter as tk
        return tk

    def _make_frame(self) -> Any:
        tk = self._tk()
        frame = tk.Frame(self._root, bg=BG)
        frame.pack(fill="both", expand=True)
        return frame

    @staticmethod
    def _set_text(widget: Any, text: str) -> None:
        try:
            current = widget.cget("text")
        except Exception:
            current = None
        if current != text:
            widget.config(text=text)

    def _clear(self) -> None:
        for child in self._frame.winfo_children():
            child.destroy()

    def _ui_after(self, callback: Any) -> None:
        try:
            self._root.after(0, callback)
        except Exception:
            callback()

    # ------------------------------------------------------------------
    # Data / render
    def _data(self) -> GuiData:
        try:
            today = self._runtime.ctx.clock.now().date()
        except AttributeError:
            # Headless regressietests monkeypatchen build_gui_data met één arg.
            return build_gui_data(self._runtime)

        if self._agenda_day is None:
            self._agenda_day = today
        elif self._last_today is not None and self._agenda_day == self._last_today and today != self._last_today:
            # "Vandaag" volgt middernacht; een bewust gekozen andere dag blijft staan.
            self._agenda_day = today
            self._agenda_page = 0
        self._last_today = today
        return build_gui_data(self._runtime, self._agenda_day, self._agenda_page)

    def render(self) -> dict:
        try:
            wanted_theme = str(self._runtime.ctx.settings.display.theme)
        except Exception:
            wanted_theme = self._active_theme
        if wanted_theme != self._active_theme:
            self._active_theme = wanted_theme
            _set_theme_palette(wanted_theme)
            try:
                self._root.config(bg=BG)
                self._frame.config(bg=BG)
            except Exception:
                pass
            self._screen = None

        layout = layout_for(self._nav, self._data())
        if layout["screen"] != self._screen:
            self._rebuild(layout)
        elif layout["screen"] == ScreenId.MAIN.value:
            self._update_main(layout)
        elif layout["screen"] == ScreenId.AGENDA.value:
            self._update_agenda(layout)
        elif layout["screen"] == ScreenId.ALARM.value:
            self._update_alarm_screen(layout)
        else:
            self._update_settings(layout)
        return layout

    def _rebuild(self, layout: dict) -> None:
        self._clear()
        # Overlay-afbeeldingen leven buiten _frame en mogen niet per tick verdwijnen.
        keep = {k: v for k, v in self._widgets.items() if k.startswith("_overlay_")}
        self._widgets = keep
        self._screen = layout["screen"]
        if self._screen == ScreenId.MAIN.value:
            self._build_main(layout)
        elif self._screen == ScreenId.AGENDA.value:
            self._build_agenda(layout)
        elif self._screen == ScreenId.ALARM.value:
            self._build_alarm_screen(layout)
        else:
            self._build_settings(layout)

    def _brand_photo(self, max_size: tuple[int, int] = (112, 43)) -> Any | None:
        """Laad het goedgekeurde C9-logo passend bij het actieve thema."""
        try:
            from PIL import Image, ImageTk
            name = "wakesync-logo.png" if self._active_theme == "light" else "wakesync-logo-dark.png"
            path = Path(__file__).resolve().parents[1] / "assets" / name
            image = Image.open(path).convert("RGBA")
            image.thumbnail(max_size, Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(image)
        except Exception:
            return None

    def _top_title(self, title: str, subtitle: str = "") -> None:
        tk = self._tk()
        top = tk.Frame(self._frame, bg=BG)
        top.pack(fill="x", padx=24, pady=(9, 2))
        tk.Label(
            top, text=title, font=("DejaVu Sans", 22, "bold"), fg=TEXT, bg=BG,
        ).pack(side="left")
        photo = self._brand_photo()
        if photo is not None:
            logo = tk.Label(top, image=photo, bg=BG, bd=0)
            logo.pack(side="right", padx=(12, 0))
            self._widgets["_brand_header_photo"] = photo
        if subtitle:
            tk.Label(
                top, text=subtitle, font=("DejaVu Sans", 9), fg=MUTED, bg=BG,
            ).pack(side="right", pady=(7, 0))

    # ------------------------------------------------------------------
    # Hoofdscherm "Vandaag"
    def _build_main(self, layout: dict) -> None:
        tk = self._tk()
        self._top_title("Vandaag", layout.get("agenda_status", ""))
        self._render_nav()

        body = tk.Frame(self._frame, bg=BG)
        body.pack(fill="both", expand=True, padx=24, pady=(3, 2))

        left = tk.Frame(body, bg=CARD)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        right = tk.Frame(body, bg=CARD)
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))

        time_label = tk.Label(
            left, text=layout["time"], font=("DejaVu Sans", 68, "bold"),
            fg=TEXT, bg=CARD,
        )
        time_label.pack(pady=(28, 4))
        tk.Label(
            left, text="VOLGEND ALARM", font=("DejaVu Sans", 9, "bold"),
            fg=MUTED, bg=CARD,
        ).pack()
        alarm_line = tk.Frame(left, bg=CARD)
        alarm_line.pack(pady=(3, 0))
        alarm_label = tk.Label(
            alarm_line, text=layout["alarm"], font=("DejaVu Sans", 21, "bold"),
            fg=ACCENT, bg=CARD,
        )
        alarm_label.pack(side="left")
        alarm_day = tk.Label(
            alarm_line, text=f' · {layout.get("alarm_day", "")}',
            font=("DejaVu Sans", 11, "bold"), fg=MUTED, bg=CARD,
        )
        alarm_day.pack(side="left", pady=(6, 0))

        lesson_label = tk.Label(
            right, text=layout["lesson_label"], font=("DejaVu Sans", 10, "bold"),
            fg=ACCENT, bg=CARD,
        )
        lesson_label.pack(anchor="w", padx=18, pady=(18, 5))
        lesson_subject = tk.Label(
            right, text=_short(layout["lesson_subject"], 42),
            font=("DejaVu Sans", 19, "bold"), fg=TEXT, bg=CARD,
            anchor="w", justify="left", wraplength=335,
        )
        lesson_subject.pack(fill="x", padx=18)
        lesson_time = tk.Label(
            right, text=layout.get("lesson_time", ""),
            font=("DejaVu Sans", 12, "bold"), fg=MUTED, bg=CARD,
        )
        lesson_time.pack(anchor="w", padx=18, pady=(6, 8))

        room_caption = tk.Label(
            right, text="LOKAAL", font=("DejaVu Sans", 9, "bold"),
            fg=MUTED, bg=CARD,
        )
        room_caption.pack(anchor="w", padx=18)
        room = tk.Label(
            right, text=_short(layout.get("lesson_room", "—"), 22),
            font=("DejaVu Sans", 27, "bold"), fg=ACCENT, bg=CARD,
        )
        room.pack(anchor="w", padx=18, pady=(0, 4))
        teacher = tk.Label(
            right,
            text=(f'Docent: {_short(layout.get("lesson_teacher", ""), 30)}'
                  if layout.get("lesson_teacher") else ""),
            font=("DejaVu Sans", 9), fg=MUTED, bg=CARD,
        )
        teacher.pack(anchor="w", padx=18)

        if layout.get("notice"):
            notice = tk.Label(
                body, text=_short(layout["notice"], 92),
                font=("DejaVu Sans", 9, "bold"), fg=DANGER, bg=BG,
            )
            notice.place(relx=0.5, rely=0.98, anchor="s")
            self._widgets["notice"] = notice

        self._widgets.update({
            "time": time_label,
            "alarm": alarm_label,
            "alarm_day": alarm_day,
            "lesson_label": lesson_label,
            "lesson_subject": lesson_subject,
            "lesson_time": lesson_time,
            "lesson_room": room,
            "lesson_teacher": teacher,
        })

    def _update_main(self, layout: dict) -> None:
        self._set_text(self._widgets["time"], layout["time"])
        self._set_text(self._widgets["alarm"], layout["alarm"])
        self._set_text(self._widgets["alarm_day"], f' · {layout.get("alarm_day", "")}')
        self._set_text(self._widgets["lesson_label"], layout["lesson_label"])
        self._set_text(self._widgets["lesson_subject"], _short(layout["lesson_subject"], 42))
        self._set_text(self._widgets["lesson_time"], layout.get("lesson_time", ""))
        self._set_text(self._widgets["lesson_room"], _short(layout.get("lesson_room", "—"), 22))
        self._set_text(
            self._widgets["lesson_teacher"],
            f'Docent: {_short(layout.get("lesson_teacher", ""), 30)}'
            if layout.get("lesson_teacher") else "",
        )
        notice = self._widgets.get("notice")
        if notice is not None:
            self._set_text(notice, _short(layout.get("notice", ""), 92))

    # ------------------------------------------------------------------
    # Volledige agenda met paginering
    def _build_agenda(self, layout: dict) -> None:
        tk = self._tk()
        self._top_title("Agenda", layout.get("provider", ""))
        self._render_nav()

        selector = tk.Frame(self._frame, bg=BG)
        selector.pack(fill="x", padx=24, pady=(0, 2))
        tk.Button(
            selector, text="‹ dag", font=("DejaVu Sans", 11, "bold"),
            fg=TEXT, bg=CARD, activebackground=CARD_ALT, activeforeground=TEXT,
            bd=0, padx=12, pady=7, command=lambda: self._shift_agenda_day(-1),
        ).pack(side="left")
        day = tk.Button(
            selector, text=layout["day"], font=("DejaVu Sans", 15, "bold"),
            fg=TEXT, bg=BG, activebackground=BG, activeforeground=ACCENT,
            bd=0, command=self._agenda_today,
        )
        day.pack(side="left", expand=True, fill="x")
        tk.Button(
            selector, text="dag ›", font=("DejaVu Sans", 11, "bold"),
            fg=TEXT, bg=CARD, activebackground=CARD_ALT, activeforeground=TEXT,
            bd=0, padx=12, pady=7, command=lambda: self._shift_agenda_day(1),
        ).pack(side="right")
        self._widgets["day"] = day

        meta = tk.Frame(self._frame, bg=BG)
        meta.pack(fill="x", padx=24, pady=(1, 3))
        status = tk.Label(
            meta, text=layout.get("status_text", ""), font=("DejaVu Sans", 8),
            fg=MUTED, bg=BG, anchor="w",
        )
        status.pack(side="left")
        page_label = tk.Label(
            meta,
            text=f'Pagina {layout["page"] + 1}/{layout["page_count"]} · {layout["total_rows"]} lessen',
            font=("DejaVu Sans", 8, "bold"), fg=MUTED, bg=BG,
        )
        page_label.pack(side="right", padx=(8, 0))
        page_prev = tk.Button(
            meta, text="‹", font=("DejaVu Sans", 10, "bold"), fg=TEXT, bg=CARD,
            bd=0, padx=10, pady=2, command=lambda: self._shift_agenda_page(-1),
            state=("normal" if layout["page"] > 0 else "disabled"),
        )
        page_prev.pack(side="right", padx=2)
        page_next = tk.Button(
            meta, text="›", font=("DejaVu Sans", 10, "bold"), fg=TEXT, bg=CARD,
            bd=0, padx=10, pady=2, command=lambda: self._shift_agenda_page(1),
            state=("normal" if layout["page"] + 1 < layout["page_count"] else "disabled"),
        )
        page_next.pack(side="right", padx=2)
        self._widgets.update({
            "agenda_status": status, "page_label": page_label,
            "page_prev": page_prev, "page_next": page_next,
        })

        content = tk.Frame(self._frame, bg=BG)
        content.pack(fill="both", expand=True, padx=24)

        if layout["simulated"] and layout["rows"]:
            badge = tk.Label(
                content, text="VOORBEELDDATA", font=("DejaVu Sans", 8, "bold"),
                fg="#102033", bg="#f5c95d", padx=7, pady=2,
            )
            badge.pack(anchor="e", pady=(0, 2))
            self._widgets["badge"] = badge

        if layout["empty_text"]:
            empty = tk.Label(
                content, text=layout["empty_text"],
                font=("DejaVu Sans", 20, "bold"), fg=MUTED, bg=CARD,
                pady=50,
            )
            empty.pack(fill="x", pady=12)
            self._widgets["empty"] = empty

        rows = []
        for row in layout["rows"]:
            row_bg = ACCENT_DARK if row.get("current") else CARD_ALT
            card = tk.Frame(content, bg=row_bg)
            card.pack(fill="x", pady=2)

            time_label = tk.Label(
                card, text=f'{row["start"]} – {row["end"]}',
                font=("DejaVu Sans", 12, "bold"), fg=ACCENT if not row.get("current") else TEXT,
                bg=row_bg, width=13, anchor="w",
            )
            time_label.pack(side="left", padx=(9, 4), pady=4)

            info = tk.Frame(card, bg=row_bg)
            info.pack(side="left", fill="both", expand=True, pady=2)
            subject = tk.Label(
                info, text=_short(row["subject"], 38),
                font=("DejaVu Sans", 12, "bold"), fg=TEXT, bg=row_bg,
                anchor="w",
            )
            subject.pack(fill="x")
            meta_parts = []
            if row.get("relation_before"):
                meta_parts.append(row["relation_before"])
            if row.get("teacher"):
                meta_parts.append(f'Docent: {row["teacher"]}')
            meta_label = tk.Label(
                info, text=" · ".join(meta_parts), font=("DejaVu Sans", 8, "bold"),
                fg=MUTED if not row.get("current") else TEXT, bg=row_bg, anchor="w",
            )
            meta_label.pack(fill="x")

            room = tk.Label(
                card, text=f'LOKAAL\n{_short(row.get("room") or "—", 16)}',
                font=("DejaVu Sans", 9, "bold"), fg=TEXT, bg=CARD,
                padx=8, pady=3, width=14, justify="center",
            )
            room.pack(side="right", padx=8)

            rows.append({
                "card": card, "time": time_label, "subject": subject,
                "meta": meta_label, "room": room,
                "current": bool(row.get("current")),
                "relation": str(row.get("relation_before") or ""),
            })
        self._widgets["rows"] = rows
        self._widgets["_agenda_page"] = layout["page"]

    def _update_agenda(self, layout: dict) -> None:
        rows = self._widgets.get("rows", [])
        structural = (
            len(rows) != len(layout["rows"])
            or self._widgets.get("_agenda_page") != layout["page"]
            or bool(self._widgets.get("badge")) != bool(layout["simulated"] and layout["rows"])
            or bool(self._widgets.get("empty")) != bool(layout["empty_text"])
            or any(
                bool(w.get("current")) != bool(r.get("current"))
                or w.get("relation") != str(r.get("relation_before") or "")
                for w, r in zip(rows, layout["rows"])
            )
        )
        if structural:
            self._rebuild(layout)
            return

        self._set_text(self._widgets["day"], layout["day"])
        self._set_text(self._widgets["agenda_status"], layout.get("status_text", ""))
        self._set_text(
            self._widgets["page_label"],
            f'Pagina {layout["page"] + 1}/{layout["page_count"]} · {layout["total_rows"]} lessen',
        )
        if layout["empty_text"]:
            self._set_text(self._widgets["empty"], layout["empty_text"])

        for widgets, row in zip(rows, layout["rows"]):
            self._set_text(widgets["time"], f'{row["start"]} – {row["end"]}')
            self._set_text(widgets["subject"], _short(row["subject"], 38))
            meta_parts = []
            if row.get("relation_before"):
                meta_parts.append(row["relation_before"])
            if row.get("teacher"):
                meta_parts.append(f'Docent: {row["teacher"]}')
            self._set_text(widgets["meta"], " · ".join(meta_parts))
            self._set_text(
                widgets["room"],
                f'LOKAAL\n{_short(row.get("room") or "—", 16)}',
            )

    def _shift_agenda_day(self, days: int) -> None:
        base = self._agenda_day or self._runtime.ctx.clock.now().date()
        self._agenda_day = base + timedelta(days=days)
        self._agenda_page = 0
        self.render()

    def _agenda_today(self) -> None:
        self._agenda_day = self._runtime.ctx.clock.now().date()
        self._agenda_page = 0
        self.render()

    def _shift_agenda_page(self, delta: int) -> None:
        data = self._data().agenda
        self._agenda_page = max(0, min(data.page + delta, data.page_count - 1))
        self.render()

    # ------------------------------------------------------------------
    # Alarm instellen met 360° klokkeuze
    @staticmethod
    def _split_alarm_time(value: str) -> tuple[int, int]:
        try:
            hour_text, minute_text = value.split(":", 1)
            return int(hour_text) % 24, int(minute_text) % 60
        except Exception:
            return 7, 30

    def _build_alarm_screen(self, layout: dict) -> None:
        tk = self._tk()
        self._top_title("Alarm", "360° tijdkiezer")
        self._render_nav()

        body_frame = tk.Frame(self._frame, bg=BG)
        body_frame.pack(fill="both", expand=True, padx=20, pady=(2, 2))

        left = tk.Frame(body_frame, bg=CARD)
        left.pack(side="left", fill="both", expand=True, padx=(0, 5))
        right = tk.Frame(body_frame, bg=CARD)
        right.pack(side="left", fill="both", expand=True, padx=(5, 0))

        mode_bar = tk.Frame(left, bg=CARD)
        mode_bar.pack(fill="x", padx=12, pady=(8, 0))
        hour_btn = tk.Button(
            mode_bar, text="Uren", font=("DejaVu Sans", 9, "bold"),
            fg=TEXT, bg=ACCENT_DARK, bd=0, padx=12, pady=4,
            command=lambda: self._set_alarm_picker_mode("hour"),
        )
        hour_btn.pack(side="left", expand=True, fill="x", padx=(0, 3))
        minute_btn = tk.Button(
            mode_bar, text="Minuten", font=("DejaVu Sans", 9, "bold"),
            fg=TEXT, bg=CARD_ALT, bd=0, padx=12, pady=4,
            command=lambda: self._set_alarm_picker_mode("minute"),
        )
        minute_btn.pack(side="left", expand=True, fill="x", padx=(3, 0))

        canvas = tk.Canvas(
            left, width=286, height=258, bg=CARD, highlightthickness=0, bd=0
        )
        canvas.pack(padx=6, pady=(0, 4))
        canvas.bind("<Button-1>", self._alarm_dial_click)

        config = tk.Frame(right, bg=CARD)
        config.pack(fill="both", expand=True, padx=12, pady=9)

        enabled = tk.Button(
            config, text="", font=("DejaVu Sans", 10, "bold"),
            fg=TEXT, bg=ACCENT_DARK, activebackground=ACCENT,
            activeforeground=TEXT, bd=0, padx=10, pady=7,
            command=self._toggle_alarm_enabled,
        )
        enabled.pack(fill="x", pady=(0, 5))

        time_value = tk.Label(
            config, text=layout["time"], font=("DejaVu Sans", 27, "bold"),
            fg=ACCENT, bg=CARD,
        )
        time_value.pack(pady=(0, 6))

        def compact_row(label_text: str) -> Any:
            row = tk.Frame(config, bg=CARD_ALT)
            row.pack(fill="x", pady=2)
            tk.Label(
                row, text=label_text, font=("DejaVu Sans", 8, "bold"),
                fg=MUTED, bg=CARD_ALT, width=13, anchor="w",
            ).pack(side="left", padx=(8, 4), pady=5)
            return row

        snooze_row = compact_row("Snooze")
        snooze = tk.Button(
            snooze_row, text="", font=("DejaVu Sans", 9, "bold"),
            fg=TEXT, bg=CARD_ALT, bd=0, padx=8,
            command=self._cycle_snooze,
        )
        snooze.pack(side="right", padx=5)

        volume_row = compact_row("Volume")
        volume = tk.Label(
            volume_row, text="", font=("DejaVu Sans", 9, "bold"),
            fg=TEXT, bg=CARD_ALT, width=6,
        )
        volume.pack(side="right", padx=2)
        tk.Button(
            volume_row, text="+", font=("DejaVu Sans", 9, "bold"),
            fg=TEXT, bg=CARD, bd=0, width=3,
            command=lambda: self._adjust_alarm_value("volume", 10, 0, 100),
        ).pack(side="right", padx=2, pady=3)
        tk.Button(
            volume_row, text="−", font=("DejaVu Sans", 9, "bold"),
            fg=TEXT, bg=CARD, bd=0, width=3,
            command=lambda: self._adjust_alarm_value("volume", -10, 0, 100),
        ).pack(side="right", padx=2, pady=3)

        speaker_row = compact_row("Speaker")
        speaker = tk.Button(
            speaker_row, text="", font=("DejaVu Sans", 9, "bold"),
            fg=TEXT, bg=CARD_ALT, bd=0, padx=8,
            command=lambda: self._toggle_alarm_bool("speaker_enabled"),
        )
        speaker.pack(side="right", padx=5)

        lamp_row = compact_row("Lamp")
        lamp = tk.Button(
            lamp_row, text="", font=("DejaVu Sans", 9, "bold"),
            fg=TEXT, bg=CARD_ALT, bd=0, padx=8,
            command=lambda: self._toggle_alarm_bool("lamp_blink"),
        )
        lamp.pack(side="right", padx=5)

        lamp_power_row = compact_row("Lampsterkte")
        lamp_power = tk.Label(
            lamp_power_row, text="", font=("DejaVu Sans", 9, "bold"),
            fg=TEXT, bg=CARD_ALT, width=6,
        )
        lamp_power.pack(side="right", padx=2)
        tk.Button(
            lamp_power_row, text="+", font=("DejaVu Sans", 9, "bold"),
            fg=TEXT, bg=CARD, bd=0, width=3,
            command=lambda: self._adjust_alarm_value("lamp_brightness", 10, 0, 100),
        ).pack(side="right", padx=2, pady=3)
        tk.Button(
            lamp_power_row, text="−", font=("DejaVu Sans", 9, "bold"),
            fg=TEXT, bg=CARD, bd=0, width=3,
            command=lambda: self._adjust_alarm_value("lamp_brightness", -10, 0, 100),
        ).pack(side="right", padx=2, pady=3)

        effect_row = compact_row("Lampeffect")
        effect = tk.Button(
            effect_row, text="", font=("DejaVu Sans", 9, "bold"),
            fg=TEXT, bg=CARD_ALT, bd=0, padx=8,
            command=self._cycle_blink_pattern,
        )
        effect.pack(side="right", padx=5)

        ramp_row = compact_row("Opbouw")
        ramp = tk.Button(
            ramp_row, text="", font=("DejaVu Sans", 9, "bold"),
            fg=TEXT, bg=CARD_ALT, bd=0, padx=8,
            command=self._cycle_ramp,
        )
        ramp.pack(side="right", padx=5)

        self._widgets.update({
            "alarm_dial": canvas,
            "alarm_hour_mode": hour_btn,
            "alarm_minute_mode": minute_btn,
            "alarm_enabled": enabled,
            "alarm_time": time_value,
            "alarm_snooze": snooze,
            "alarm_volume": volume,
            "alarm_speaker": speaker,
            "alarm_lamp": lamp,
            "alarm_lamp_brightness": lamp_power,
            "alarm_effect": effect,
            "alarm_ramp": ramp,
        })
        self._update_alarm_screen(layout)

    def _set_alarm_picker_mode(self, mode: str) -> None:
        self._alarm_picker_mode = "minute" if mode == "minute" else "hour"
        layout = layout_for(self._nav, self._data())
        self._update_alarm_screen(layout)

    @staticmethod
    def _angle_value(x: float, y: float, cx: float, cy: float, divisions: int) -> int:
        angle = math.atan2(y - cy, x - cx) + (math.pi / 2)
        if angle < 0:
            angle += 2 * math.pi
        return int(round(angle / (2 * math.pi) * divisions)) % divisions

    def _alarm_dial_click(self, event: Any) -> None:
        layout = layout_for(self._nav, self._data())
        hour, minute = self._split_alarm_time(layout.get("time", "07:30"))
        if self._alarm_picker_mode == "hour":
            hour = self._angle_value(float(event.x), float(event.y), 143.0, 129.0, 24)
            self._alarm_picker_mode = "minute"
        else:
            minute = self._angle_value(float(event.x), float(event.y), 143.0, 129.0, 60)
        self._save_alarm_patch({"time": f"{hour:02d}:{minute:02d}"})

    def _draw_alarm_dial(self, layout: dict) -> None:
        canvas = self._widgets.get("alarm_dial")
        if canvas is None:
            return
        canvas.delete("all")
        hour, minute = self._split_alarm_time(layout.get("time", "07:30"))
        cx, cy, radius = 143.0, 129.0, 100.0
        canvas.create_oval(
            cx-radius, cy-radius, cx+radius, cy+radius,
            outline=BORDER, width=3, fill=CARD_ALT,
        )
        mode = self._alarm_picker_mode
        divisions = 24 if mode == "hour" else 60
        selected = hour if mode == "hour" else minute
        for i in range(divisions):
            angle = (i / divisions) * 2 * math.pi - math.pi / 2
            outer = radius - 4
            inner = radius - (13 if i % (3 if mode == "hour" else 5) == 0 else 8)
            x1 = cx + math.cos(angle) * inner
            y1 = cy + math.sin(angle) * inner
            x2 = cx + math.cos(angle) * outer
            y2 = cy + math.sin(angle) * outer
            canvas.create_line(
                x1, y1, x2, y2,
                fill=ACCENT if i == selected else MUTED,
                width=3 if i == selected else 1,
            )
            label_step = 3 if mode == "hour" else 5
            if i % label_step == 0:
                lr = radius - 29
                lx = cx + math.cos(angle) * lr
                ly = cy + math.sin(angle) * lr
                canvas.create_text(
                    lx, ly, text=f"{i:02d}",
                    fill=TEXT if i == selected else MUTED,
                    font=("DejaVu Sans", 8, "bold" if i == selected else "normal"),
                )

        value = selected
        angle = (value / divisions) * 2 * math.pi - math.pi / 2
        hand_r = radius - 40
        hx = cx + math.cos(angle) * hand_r
        hy = cy + math.sin(angle) * hand_r
        canvas.create_line(cx, cy, hx, hy, fill=ACCENT, width=5, capstyle="round")
        canvas.create_oval(cx-7, cy-7, cx+7, cy+7, fill=ACCENT, outline=ACCENT)
        canvas.create_text(
            cx, cy+43,
            text=("UUR" if mode == "hour" else "MINUUT"),
            fill=MUTED, font=("DejaVu Sans", 8, "bold"),
        )

        hour_button = self._widgets.get("alarm_hour_mode")
        minute_button = self._widgets.get("alarm_minute_mode")
        if hour_button is not None:
            hour_button.config(bg=ACCENT_DARK if mode == "hour" else CARD_ALT)
        if minute_button is not None:
            minute_button.config(bg=ACCENT_DARK if mode == "minute" else CARD_ALT)

    def _save_alarm_patch(self, patch: dict[str, Any]) -> None:
        try:
            nieuwe = self._runtime.ctx.settings.update_from_dict({"alarm": patch})
            from wekker.main import apply_runtime_settings
            apply_runtime_settings(self._runtime, nieuwe)
        except Exception as exc:
            log.exception("alarminstellingen opslaan faalde")
            self._show_toast(f"Opslaan mislukt: {exc}", error=True)
            return
        self._last_activity = time.monotonic()
        self._show_toast("Alarm opgeslagen")
        self.render()

    def _toggle_alarm_enabled(self) -> None:
        current = bool(self._runtime.ctx.settings.alarm.enabled)
        self._save_alarm_patch({"enabled": not current})

    def _toggle_alarm_bool(self, field: str) -> None:
        current = bool(getattr(self._runtime.ctx.settings.alarm, field))
        self._save_alarm_patch({field: not current})

    def _adjust_alarm_value(self, field: str, delta: int, low: int, high: int) -> None:
        current = int(getattr(self._runtime.ctx.settings.alarm, field))
        value = max(low, min(high, current + delta))
        self._save_alarm_patch({field: value})

    def _cycle_snooze(self) -> None:
        values = [5, 9, 10, 15, 20, 30]
        current = int(self._runtime.ctx.settings.alarm.snooze_minutes)
        try:
            idx = values.index(current)
        except ValueError:
            idx = 0
        self._save_alarm_patch({"snooze_minutes": values[(idx + 1) % len(values)]})

    def _cycle_blink_pattern(self) -> None:
        values = ["steady", "blink", "pulse"]
        current = str(self._runtime.ctx.settings.alarm.blink_pattern)
        try:
            idx = values.index(current)
        except ValueError:
            idx = 0
        self._save_alarm_patch({"blink_pattern": values[(idx + 1) % len(values)]})

    def _cycle_ramp(self) -> None:
        values = [0, 15, 30, 60, 120]
        current = int(self._runtime.ctx.settings.alarm.ramp_up_seconds)
        try:
            idx = values.index(current)
        except ValueError:
            idx = 0
        self._save_alarm_patch({"ramp_up_seconds": values[(idx + 1) % len(values)]})

    def _update_alarm_screen(self, layout: dict) -> None:
        if self._widgets.get("alarm_time") is None:
            return
        self._set_text(self._widgets["alarm_time"], layout["time"])
        self._set_text(
            self._widgets["alarm_enabled"],
            "Alarm AAN" if layout.get("enabled") else "Alarm UIT",
        )
        self._widgets["alarm_enabled"].config(
            bg=ACCENT_DARK if layout.get("enabled") else CARD_ALT
        )
        self._set_text(
            self._widgets["alarm_snooze"], f'{layout.get("snooze_minutes", 9)} min'
        )
        self._set_text(self._widgets["alarm_volume"], f'{layout.get("volume", 70)}%')
        self._set_text(
            self._widgets["alarm_speaker"],
            "Aan" if layout.get("speaker_enabled") else "Uit",
        )
        self._set_text(
            self._widgets["alarm_lamp"],
            "Aan" if layout.get("lamp_blink") else "Uit",
        )
        self._set_text(
            self._widgets["alarm_lamp_brightness"],
            f'{layout.get("lamp_brightness", 100)}%',
        )
        patterns = {"steady": "Constant", "blink": "Knipperen", "pulse": "Pulseren"}
        self._set_text(
            self._widgets["alarm_effect"],
            patterns.get(layout.get("blink_pattern"), "Knipperen"),
        )
        self._set_text(
            self._widgets["alarm_ramp"], f'{layout.get("ramp_up_seconds", 30)} sec'
        )
        self._draw_alarm_dial(layout)

    # ------------------------------------------------------------------
    # Instellingen per onderwerp
    def _build_settings(self, layout: dict) -> None:
        tk = self._tk()
        self._top_title("Instellingen", "Kies een onderwerp")
        self._render_nav()

        body = tk.Frame(self._frame, bg=BG)
        body.pack(fill="both", expand=True, padx=34, pady=(9, 4))

        rows = [
            (("Weergave", "Tijd, thema en slaapmodus", lambda: self._show_settings_section("display")),
             ("Online beheer", "QR, login en synchronisatie", lambda: self._show_settings_section("cloud"))),
            (("Software", "Versie en veilige updater", self._show_update_overlay),
             ("Diagnose", "Sync, systeemtijd en update-status", lambda: self._show_settings_section("diagnostics"))),
        ]
        buttons = []
        for pair in rows:
            row = tk.Frame(body, bg=BG)
            row.pack(fill="x", pady=5)
            for idx, item in enumerate(pair):
                if item is None:
                    spacer = tk.Frame(row, bg=BG)
                    spacer.pack(side="left", fill="x", expand=True, padx=5)
                    continue
                title, subtitle, command = item
                card = tk.Button(
                    row,
                    text=f"{title}\n{subtitle}",
                    font=("DejaVu Sans", 11, "bold"),
                    fg=TEXT, bg=CARD, activebackground=ACCENT_DARK,
                    activeforeground=TEXT, bd=0, justify="left", anchor="w",
                    padx=16, pady=10, command=command,
                )
                card.pack(side="left", fill="x", expand=True, padx=5)
                buttons.append(card)

        cloud_summary = tk.Label(
            body,
            text=layout.get("cloud_status", ""),
            font=("DejaVu Sans", 9), fg=SUCCESS if layout.get("cloud_ready") else MUTED,
            bg=BG,
        )
        cloud_summary.pack(anchor="w", padx=6, pady=(7, 0))
        self._widgets["settings_cloud_summary"] = cloud_summary
        self._widgets["settings_buttons"] = buttons

    def _update_settings(self, layout: dict) -> None:
        summary = self._widgets.get("settings_cloud_summary")
        if summary is not None:
            self._set_text(summary, layout.get("cloud_status", ""))
        if self._settings_overlay is not None and self._settings_section == "cloud":
            self._update_cloud_section(layout)

    def _show_settings_section(self, section: str) -> None:
        self._close_settings_section()
        self._last_activity = time.monotonic()
        tk = self._tk()
        overlay = tk.Frame(self._root, bg=BG)
        overlay.place(x=0, y=0, relwidth=1, relheight=1)
        try:
            overlay.lift()
        except Exception:
            pass
        self._settings_overlay = overlay
        self._settings_section = section

        top = tk.Frame(overlay, bg=BG)
        top.pack(fill="x", padx=22, pady=(14, 6))
        tk.Button(
            top, text="‹ Terug", font=("DejaVu Sans", 11, "bold"),
            fg=TEXT, bg=CARD, activebackground=ACCENT_DARK, activeforeground=TEXT,
            bd=0, padx=14, pady=8, command=self._close_settings_section,
        ).pack(side="left")
        titles = {
            "display": "Weergave",
            "cloud": "Online beheer",
            "diagnostics": "Diagnose",
        }
        tk.Label(
            top, text=titles.get(section, "Instellingen"),
            font=("DejaVu Sans", 22, "bold"), fg=TEXT, bg=BG,
        ).pack(side="left", padx=18)

        layout = layout_for(self._nav, self._data())
        if section == "display":
            self._build_display_section(overlay, layout)
        elif section == "cloud":
            self._build_cloud_section(overlay, layout)
        elif section == "diagnostics":
            self._build_diagnostics_section(overlay)

    def _close_settings_section(self) -> None:
        overlay = self._settings_overlay
        self._settings_overlay = None
        self._settings_section = None
        if overlay is not None:
            try:
                overlay.destroy()
            except Exception:
                pass
        for key in list(self._widgets):
            if key.startswith("_section_"):
                self._widgets.pop(key, None)

    def _build_display_section(self, parent: Any, layout: dict) -> None:
        tk = self._tk()
        body = tk.Frame(parent, bg=BG)
        body.pack(fill="both", expand=True, padx=34, pady=(6, 20))

        def card(title: str) -> Any:
            frame = tk.Frame(body, bg=CARD)
            frame.pack(fill="x", pady=5)
            tk.Label(
                frame, text=title, font=("DejaVu Sans", 11, "bold"),
                fg=MUTED, bg=CARD, width=18, anchor="w",
            ).pack(side="left", padx=14, pady=11)
            return frame

        zone_card = card("Tijdzone")
        labels = [label for _, label in TIMEZONE_CHOICES]
        self._zone_by_label = {label: value for value, label in TIMEZONE_CHOICES}
        zone_var = tk.StringVar(value=self._timezone_label(layout["timezone"]))
        zone_menu = tk.OptionMenu(zone_card, zone_var, *labels, command=self._select_timezone)
        zone_menu.config(
            font=("DejaVu Sans", 10, "bold"), fg=TEXT, bg=CARD_ALT,
            activebackground=ACCENT_DARK, activeforeground=TEXT, bd=0,
            highlightthickness=0, padx=8, pady=5,
        )
        zone_menu.pack(side="right", fill="x", expand=True, padx=12, pady=6)

        fmt = card("Tijdsweergave")
        tk.Button(
            fmt, text=self._format_label(layout["time_format"]),
            font=("DejaVu Sans", 10, "bold"), fg=TEXT, bg=CARD_ALT,
            activebackground=ACCENT_DARK, activeforeground=TEXT, bd=0,
            padx=12, pady=6, command=self._toggle_time_format,
        ).pack(side="right", padx=12, pady=6)

        theme_card = card("Thema")
        theme_labels = [label for _, label in THEME_CHOICES]
        self._theme_by_label = {label: value for value, label in THEME_CHOICES}
        theme_var = tk.StringVar(value=self._theme_label(layout.get("theme", "midnight")))
        theme_menu = tk.OptionMenu(
            theme_card, theme_var, *theme_labels, command=self._select_theme
        )
        theme_menu.config(
            font=("DejaVu Sans", 10, "bold"), fg=TEXT, bg=CARD_ALT,
            activebackground=ACCENT_DARK, activeforeground=TEXT, bd=0,
            highlightthickness=0, padx=8, pady=5,
        )
        theme_menu.pack(side="right", padx=12, pady=6)

        sleep = card("Slaapmodus")
        sleep_labels = [label for _, label in SLEEP_AFTER_CHOICES]
        self._sleep_after_by_label = {label: value for value, label in SLEEP_AFTER_CHOICES}
        sleep_var = tk.StringVar(
            value=self._sleep_after_label(layout.get("sleep_after_seconds", 60))
        )
        sleep_menu = tk.OptionMenu(
            sleep, sleep_var, *sleep_labels, command=self._select_sleep_after
        )
        sleep_menu.config(
            font=("DejaVu Sans", 10, "bold"), fg=TEXT, bg=CARD_ALT,
            activebackground=ACCENT_DARK, activeforeground=TEXT, bd=0,
            highlightthickness=0, padx=8, pady=5,
        )
        sleep_menu.pack(side="right", padx=12, pady=6)
        view = tk.Button(
            sleep, text=self._sleep_view_label(layout.get("sleep_view", "logo_time_date")),
            font=("DejaVu Sans", 9, "bold"), fg=TEXT, bg=CARD_ALT,
            bd=0, padx=10, pady=6, command=self._cycle_sleep_view,
        )
        view.pack(side="right", padx=(4, 0), pady=6)
        self._widgets["_section_sleep_view"] = view

        effect_card = card("Slaapeffect")
        effect_labels = [label for _, label in SLEEP_EFFECT_CHOICES]
        self._sleep_effect_by_label = {label: value for value, label in SLEEP_EFFECT_CHOICES}
        effect_var = tk.StringVar(
            value=self._sleep_effect_label(layout.get("sleep_effect", "soft_glow"))
        )
        effect_menu = tk.OptionMenu(
            effect_card, effect_var, *effect_labels, command=self._select_sleep_effect
        )
        effect_menu.config(
            font=("DejaVu Sans", 9, "bold"), fg=TEXT, bg=CARD_ALT,
            activebackground=ACCENT_DARK, activeforeground=TEXT, bd=0,
            highlightthickness=0, padx=8, pady=5,
        )
        effect_menu.pack(side="right", padx=12, pady=6)
        intensity = tk.Button(
            effect_card,
            text=f'Gloed {int(layout.get("sleep_glow_intensity", 65))}%',
            font=("DejaVu Sans", 9, "bold"), fg=TEXT, bg=CARD_ALT,
            bd=0, padx=10, pady=6, command=self._cycle_sleep_intensity,
        )
        intensity.pack(side="right", padx=(4, 0), pady=6)
        self._widgets["_section_sleep_intensity"] = intensity

    def _build_cloud_section(self, parent: Any, layout: dict) -> None:
        tk = self._tk()
        body = tk.Frame(parent, bg=CARD)
        body.pack(fill="both", expand=True, padx=34, pady=(8, 24))

        status = tk.Label(
            body, text=layout.get("cloud_status", ""),
            font=("DejaVu Sans", 11, "bold"),
            fg=SUCCESS if layout.get("cloud_ready") else MUTED, bg=CARD,
        )
        status.pack(anchor="w", padx=18, pady=(16, 4))
        self._widgets["_section_cloud_status"] = status

        content = tk.Frame(body, bg=CARD)
        content.pack(fill="both", expand=True, padx=18, pady=8)
        qr = tk.Label(
            content, text="QR wordt voorbereid…", font=("DejaVu Sans", 10, "bold"),
            fg=MUTED, bg="#ffffff", width=18, height=9,
        )
        qr.pack(side="left", anchor="n", padx=(0, 18))
        qr.bind("<Button-1>", lambda _e: self._show_qr_overlay())
        self._widgets["_section_cloud_qr"] = qr

        details = tk.Frame(content, bg=CARD)
        details.pack(side="left", fill="both", expand=True)
        url = tk.Label(
            details, text=layout.get("cloud_url") or "Wordt lokaal aangemaakt…",
            font=("DejaVu Sans", 9), fg=ACCENT, bg=CARD,
            anchor="w", justify="left", wraplength=420,
        )
        url.pack(fill="x", pady=(4, 12))
        user = tk.Label(
            details, text=f'Gebruikersnaam: {layout.get("cloud_username", "basis")}',
            font=("DejaVu Sans", 11, "bold"), fg=TEXT, bg=CARD, anchor="w",
        )
        user.pack(fill="x", pady=2)
        password = tk.Label(
            details, text=self._cloud_password_text(layout),
            font=("DejaVu Sans Mono", 10, "bold"), fg=TEXT, bg=CARD, anchor="w",
        )
        password.pack(fill="x", pady=2)
        meta = tk.Label(
            details, text=self._cloud_meta_text(layout),
            font=("DejaVu Sans", 9), fg=MUTED, bg=CARD, anchor="w",
        )
        meta.pack(fill="x", pady=(8, 0))
        tk.Label(
            details,
            text="Tik op de QR-code om hem schermvullend te tonen.",
            font=("DejaVu Sans", 9), fg=MUTED, bg=CARD, anchor="w",
        ).pack(fill="x", pady=(10, 0))
        self._widgets.update({
            "_section_cloud_url": url,
            "_section_cloud_user": user,
            "_section_cloud_password": password,
            "_section_cloud_meta": meta,
            "_section_qr_url": layout.get("cloud_url") or "",
        })
        self._refresh_section_qr(layout)

    def _update_cloud_section(self, layout: dict) -> None:
        for key, text in (
            ("_section_cloud_status", layout.get("cloud_status", "")),
            ("_section_cloud_url", layout.get("cloud_url") or "Wordt lokaal aangemaakt…"),
            ("_section_cloud_user", f'Gebruikersnaam: {layout.get("cloud_username", "basis")}'),
            ("_section_cloud_password", self._cloud_password_text(layout)),
            ("_section_cloud_meta", self._cloud_meta_text(layout)),
        ):
            widget = self._widgets.get(key)
            if widget is not None:
                self._set_text(widget, text)
        if self._widgets.get("_section_qr_url") != (layout.get("cloud_url") or ""):
            self._refresh_section_qr(layout)

    def _build_diagnostics_section(self, parent: Any) -> None:
        tk = self._tk()
        body = tk.Frame(parent, bg=CARD)
        body.pack(fill="both", expand=True, padx=34, pady=(8, 24))
        text = tk.Label(
            body, text="Diagnose verzamelen…",
            font=("DejaVu Sans Mono", 10), fg=TEXT, bg=CARD,
            justify="left", anchor="nw", wraplength=690,
        )
        text.pack(fill="both", expand=True, padx=18, pady=(18, 8))
        export = tk.Button(
            body, text="Veilige diagnose exporteren",
            font=("DejaVu Sans", 10, "bold"), fg=TEXT, bg=ACCENT_DARK,
            bd=0, padx=14, pady=8, state="disabled",
        )
        export.pack(anchor="w", padx=18, pady=(0, 16))
        self._widgets["_section_diag_text"] = text
        self._widgets["_section_diag_export"] = export

        def worker() -> None:
            try:
                from wekker.diagnostics import collect_diagnostics
                snapshot = collect_diagnostics(self._runtime)
            except Exception as exc:
                self._ui_after(lambda: self._set_text(text, f"Diagnosefout: {exc}"))
                return

            def show() -> None:
                lines = [
                    f"WakeSync v{snapshot.version}",
                    f"Tijdzone: {snapshot.timezone}",
                    f"NTP: {snapshot.ntp_synchronized}",
                    f"Agenda: {snapshot.agenda_status}",
                    f"Laatste geslaagde sync: {snapshot.agenda_last_success or '—'}",
                    f"Laatste poging: {snapshot.agenda_last_attempt or '—'}",
                    f"Cloud: {snapshot.cloud_status}",
                    f"Display: {snapshot.display_session} · {snapshot.display_name}",
                    f"Backlight: {snapshot.backlight}",
                    f"Updater: {snapshot.update_status}",
                ]
                self._set_text(text, "\n".join(lines))
                export.config(state="normal", command=self._export_diagnostics)

            self._ui_after(show)

        threading.Thread(target=worker, name="wakesync-diagnostics", daemon=True).start()

    def _export_diagnostics(self) -> None:
        try:
            from wekker.diagnostics import export_diagnostics
            settings_path = Path(getattr(self._runtime.ctx.store, "path", "wekker-settings.json"))
            target = settings_path.resolve().with_name("wakesync-diagnose.json")
            export_diagnostics(target, self._runtime)
        except Exception as exc:
            self._show_toast(f"Export mislukt: {exc}", error=True)
            return
        self._show_toast("Diagnose opgeslagen als wakesync-diagnose.json")

    # ------------------------------------------------------------------
    # QR
    @staticmethod
    def _cloud_password_text(layout: dict) -> str:
        if layout.get("cloud_password_changed"):
            return "Wachtwoord: gewijzigd op de website"
        return f'Wachtwoord: {layout.get("cloud_password") or "wordt aangemaakt…"}'

    @staticmethod
    def _cloud_meta_text(layout: dict) -> str:
        revision = int(layout.get("cloud_revision", 0) or 0)
        last_sync = str(layout.get("cloud_last_sync", "") or "")
        if last_sync:
            return f"Revisie {revision} · laatste sync {last_sync.replace('T', ' ')[:16]} UTC"
        return f"Revisie {revision} · nog niet gesynchroniseerd"

    def _refresh_section_qr(self, layout: dict) -> None:
        widget = self._widgets.get("_section_cloud_qr")
        url = layout.get("cloud_url") or ""
        self._widgets["_section_qr_url"] = url
        if widget is None or not url:
            return
        try:
            import qrcode
            from PIL import ImageTk
            image = qrcode.make(url).resize((145, 145))
            photo = ImageTk.PhotoImage(image)
            widget.config(image=photo, text="", width=145, height=145)
            self._widgets["_section_qr_photo"] = photo
        except Exception as exc:
            log.warning("QR-code kon niet worden getekend: %s", exc)

    def _show_qr_overlay(self) -> None:
        url = str(self._widgets.get("_section_qr_url") or "")
        if not url or self._qr_overlay is not None:
            return
        tk = self._tk()
        overlay = tk.Frame(self._root, bg=BG)
        overlay.place(x=0, y=0, relwidth=1, relheight=1)
        overlay.lift()
        self._qr_overlay = overlay
        self._last_activity = time.monotonic()
        qr_top = tk.Frame(overlay, bg=BG)
        qr_top.pack(fill="x", padx=28, pady=(9, 5))
        brand = self._brand_photo((118, 44))
        if brand is not None:
            tk.Label(qr_top, image=brand, bg=BG, bd=0).pack(side="left")
            self._widgets["_overlay_qr_brand"] = brand
        tk.Label(
            qr_top, text="Online beheer", font=("DejaVu Sans", 18, "bold"),
            fg=TEXT, bg=BG,
        ).pack(side="right", pady=(8, 0))
        try:
            import qrcode
            from PIL import ImageTk
            image = qrcode.make(url).resize((320, 320))
            photo = ImageTk.PhotoImage(image)
            qr = tk.Label(overlay, image=photo, bg="#ffffff", bd=0)
            qr.pack()
            self._widgets["_overlay_qr_photo"] = photo
            qr.bind("<Button-1>", lambda _e: self._close_qr_overlay())
        except Exception:
            tk.Label(
                overlay, text=url, font=("DejaVu Sans", 11), fg=ACCENT, bg=BG,
                wraplength=700,
            ).pack(pady=80)
        tk.Label(
            overlay, text="Tik ergens om te sluiten",
            font=("DejaVu Sans", 10, "bold"), fg=MUTED, bg=BG,
        ).pack(pady=(6, 0))
        overlay.bind("<Button-1>", lambda _e: self._close_qr_overlay())

    def _close_qr_overlay(self) -> None:
        overlay = self._qr_overlay
        self._qr_overlay = None
        if overlay is not None:
            try:
                overlay.destroy()
            except Exception:
                pass
        self._widgets.pop("_overlay_qr_photo", None)
        self._widgets.pop("_overlay_qr_brand", None)

    # ------------------------------------------------------------------
    # Opslaan + feedback
    @staticmethod
    def _timezone_label(zone: str) -> str:
        return dict(TIMEZONE_CHOICES).get(zone, zone)

    @staticmethod
    def _format_label(value: str) -> str:
        return "24 uur · 20:41" if value == "24h" else "12 uur · 8:41 PM"

    @staticmethod
    def _theme_label(value: str) -> str:
        return dict(THEME_CHOICES).get(value, "Midnight")

    @staticmethod
    def _sleep_after_label(value: int) -> str:
        try:
            return dict(SLEEP_AFTER_CHOICES).get(int(value), f"{int(value)} seconden")
        except (TypeError, ValueError):
            return "1 minuut"

    @staticmethod
    def _sleep_view_label(value: str) -> str:
        return dict(SLEEP_VIEW_CHOICES).get(value, "Logo + tijd + datum")

    @staticmethod
    def _sleep_effect_label(value: str) -> str:
        return dict(SLEEP_EFFECT_CHOICES).get(value, "Zachte gloed")

    def _show_toast(self, message: str, *, error: bool = False) -> None:
        tk = self._tk()
        if self._toast is not None:
            try:
                self._toast.destroy()
            except Exception:
                pass
        toast = tk.Label(
            self._root, text=message, font=("DejaVu Sans", 11, "bold"),
            fg="#ffffff", bg=DANGER if error else "#17795a",
            padx=18, pady=9,
        )
        toast.place(relx=0.5, y=12, anchor="n")
        try:
            toast.lift()
        except Exception:
            pass
        self._toast = toast
        try:
            self._root.after(2400, lambda: self._dismiss_toast(toast))
        except Exception:
            pass

    def _dismiss_toast(self, toast: Any) -> None:
        if self._toast is toast:
            self._toast = None
        try:
            toast.destroy()
        except Exception:
            pass

    def _save_display_patch(self, patch: dict[str, Any]) -> None:
        try:
            nieuwe = self._runtime.ctx.settings.update_from_dict({"display": patch})
            from wekker.main import apply_runtime_settings
            apply_runtime_settings(self._runtime, nieuwe)
        except Exception as exc:
            log.exception("scherminstellingen opslaan faalde")
            self._show_toast(f"Opslaan mislukt: {exc}", error=True)
            return
        self._last_activity = time.monotonic()
        self._show_toast("Opgeslagen")
        self.render()

    def _select_sleep_after(self, label: str) -> None:
        value = getattr(self, "_sleep_after_by_label", {}).get(label)
        if value is not None:
            self._save_display_patch({"sleep_after_seconds": int(value)})

    def _cycle_sleep_view(self) -> None:
        current = str(self._runtime.ctx.settings.display.sleep_view)
        order = [value for value, _ in SLEEP_VIEW_CHOICES]
        try:
            index = order.index(current)
        except ValueError:
            index = 0
        value = order[(index + 1) % len(order)]
        self._save_display_patch({"sleep_view": value})
        widget = self._widgets.get("_section_sleep_view")
        if widget is not None:
            self._set_text(widget, self._sleep_view_label(value))

    def _select_sleep_effect(self, label: str) -> None:
        value = getattr(self, "_sleep_effect_by_label", {}).get(label)
        if value:
            self._save_display_patch({"sleep_effect": value})

    def _cycle_sleep_intensity(self) -> None:
        current = int(self._runtime.ctx.settings.display.sleep_glow_intensity)
        levels = list(SLEEP_GLOW_LEVELS)
        try:
            index = levels.index(current)
        except ValueError:
            index = 2
        value = levels[(index + 1) % len(levels)]
        self._save_display_patch({"sleep_glow_intensity": value})
        widget = self._widgets.get("_section_sleep_intensity")
        if widget is not None:
            self._set_text(widget, f"Gloed {value}%")

    def _select_theme(self, label: str) -> None:
        theme = getattr(self, "_theme_by_label", {}).get(label)
        if theme:
            self._save_display_patch({"theme": theme})

    def _select_timezone(self, label: str) -> None:
        zone = getattr(self, "_zone_by_label", {}).get(label)
        if zone:
            self._save_locale(timezone=zone)

    def _toggle_time_format(self) -> None:
        current = self._runtime.ctx.settings.locale.time_format
        self._save_locale(time_format="12h" if current == "24h" else "24h")

    def _save_locale(self, *, timezone: str | None = None, time_format: str | None = None) -> None:
        patch: dict[str, str] = {}
        if timezone is not None:
            patch["timezone"] = timezone
        if time_format is not None:
            patch["time_format"] = time_format
        try:
            nieuwe = self._runtime.ctx.settings.update_from_dict({"locale": patch})
            from wekker.main import apply_runtime_settings
            apply_runtime_settings(self._runtime, nieuwe)
        except Exception as exc:
            log.exception("lokale instellingen opslaan faalde")
            self._show_toast(f"Opslaan mislukt: {exc}", error=True)
            return
        self._show_toast("Opgeslagen")
        self.render()

    # ------------------------------------------------------------------
    # Software-updater
    def _show_update_overlay(self) -> None:
        if self._update_overlay is not None:
            return
        self._close_settings_section()
        self._last_activity = time.monotonic()
        tk = self._tk()
        overlay = tk.Frame(self._root, bg=BG)
        overlay.place(x=0, y=0, relwidth=1, relheight=1)
        overlay.lift()
        self._update_overlay = overlay

        from wekker import __version__
        tk.Label(
            overlay, text="Software", font=("DejaVu Sans", 24, "bold"),
            fg=TEXT, bg=BG,
        ).pack(pady=(24, 3))
        tk.Label(
            overlay, text=f"WakeSync v{__version__}",
            font=("DejaVu Sans", 11), fg=MUTED, bg=BG,
        ).pack(pady=(0, 13))

        card = tk.Frame(overlay, bg=CARD)
        card.pack(fill="x", padx=90, pady=3)
        status = tk.Label(
            card, text="Controleren op een stabiele release…",
            font=("DejaVu Sans", 13, "bold"), fg=TEXT, bg=CARD,
            justify="center", wraplength=570,
        )
        status.pack(fill="x", padx=20, pady=(20, 9))
        detail = tk.Label(
            card,
            text="Alleen gepubliceerde GitHub Releases worden standaard geïnstalleerd.",
            font=("DejaVu Sans", 9), fg=MUTED, bg=CARD,
            justify="center", wraplength=570,
        )
        detail.pack(fill="x", padx=20, pady=(0, 14))
        button = tk.Button(
            card, text="Even geduld…", state="disabled",
            font=("DejaVu Sans", 11, "bold"), fg=TEXT, bg=ACCENT_DARK,
            disabledforeground=MUTED, bd=0, padx=18, pady=8,
        )
        button.pack(pady=(0, 18))
        tk.Button(
            overlay, text="Sluiten", font=("DejaVu Sans", 11, "bold"),
            fg=TEXT, bg=CARD, bd=0, padx=24, pady=8,
            command=self._close_update_overlay,
        ).pack(pady=(13, 0))

        self._widgets["_overlay_update_status"] = status
        self._widgets["_overlay_update_detail"] = detail
        self._widgets["_overlay_update_button"] = button
        self._check_updates_async()

    def _close_update_overlay(self) -> None:
        overlay = self._update_overlay
        self._update_overlay = None
        if overlay is not None:
            try:
                overlay.destroy()
            except Exception:
                pass
        for key in list(self._widgets):
            if key.startswith("_overlay_update"):
                self._widgets.pop(key, None)

    def _check_updates_async(self) -> None:
        def worker() -> None:
            try:
                from wekker.updater import SoftwareUpdater
                updater = SoftwareUpdater()
                info = updater.check()
            except Exception as exc:
                self._ui_after(lambda: self._show_update_error(str(exc)))
                return
            self._ui_after(lambda: self._show_update_result(updater, info))
        threading.Thread(target=worker, name="wakesync-update-check", daemon=True).start()

    def _show_update_error(self, message: str) -> None:
        if self._update_overlay is None:
            return
        status = self._widgets.get("_overlay_update_status")
        detail = self._widgets.get("_overlay_update_detail")
        button = self._widgets.get("_overlay_update_button")
        if status is not None:
            self._set_text(status, "Updatecontrole niet beschikbaar")
        if detail is not None:
            self._set_text(detail, message)
        if button is not None:
            button.config(
                text="Opnieuw controleren", state="normal",
                command=self._check_updates_async,
            )

    def _show_update_result(self, updater: Any, info: Any) -> None:
        if self._update_overlay is None:
            return
        self._update_updater = updater
        self._update_info = info
        status = self._widgets.get("_overlay_update_status")
        detail = self._widgets.get("_overlay_update_detail")
        button = self._widgets.get("_overlay_update_button")
        if info.available:
            self._set_text(status, f"WakeSync v{info.latest_version} is beschikbaar")
            checksum = " · checksum aanwezig" if getattr(info, "sha256", "") else ""
            self._set_text(
                detail,
                f"Bron: {info.source}{checksum}. De update maakt eerst een backup, "
                "voert een healthcheck uit en herstart alleen op een veilig moment.",
            )
            button.config(
                text=f"Installeer v{info.latest_version}", state="normal",
                command=self._install_update_async,
            )
        else:
            self._set_text(status, "WakeSync is bijgewerkt")
            self._set_text(detail, f"Nieuwste stabiele versie: v{info.latest_version}")
            button.config(text="Geen update nodig", state="disabled")

    def _restart_safety(self) -> tuple[bool, str]:
        try:
            state = str(self._runtime.ctx.core.state.value)
            if state in {"ringing", "snoozed"}:
                return False, "Update uitgesteld: alarm is actief of gesnoozed."
            now = self._runtime.ctx.clock.now()
            nxt = self._runtime.ctx.core.next_alarm(now)
            if nxt is not None:
                delta = nxt - now
                if timedelta(0) <= delta <= timedelta(minutes=10):
                    return False, "Update uitgesteld: alarm gaat binnen 10 minuten af."
        except Exception:
            return False, "Update uitgesteld: alarmstatus kon niet veilig worden bevestigd."
        return True, ""

    def _install_update_async(self) -> None:
        safe, reason = self._restart_safety()
        if not safe:
            self._show_update_error(reason)
            return
        updater = getattr(self, "_update_updater", None)
        info = self._update_info
        if updater is None or info is None or not info.available:
            return
        button = self._widgets.get("_overlay_update_button")
        status = self._widgets.get("_overlay_update_status")
        detail = self._widgets.get("_overlay_update_detail")
        button.config(text="Downloaden en controleren…", state="disabled")
        self._set_text(status, "Update wordt voorbereid")
        self._set_text(detail, "Alarm en klok blijven actief tot de download klaar is.")

        def worker() -> None:
            try:
                args = list(sys.argv[1:])
                if not args or args[0] != "gui":
                    args = ["gui"]
                restart = [sys.executable, "-m", "wekker", *args]
                settings_path = str(getattr(self._runtime.ctx.store, "path", "wekker-settings.json"))
                updater.launch_install(
                    info,
                    restart_args=restart,
                    parent_pid=os.getpid(),
                    settings_path=settings_path,
                )
            except Exception as exc:
                self._ui_after(lambda: self._show_update_error(str(exc)))
                return

            def finish() -> None:
                if self._update_overlay is not None:
                    self._set_text(
                        self._widgets["_overlay_update_status"],
                        "Download klaar · veilige installatie wordt gestart",
                    )
                try:
                    self._root.after(500, self.stop)
                except Exception:
                    self.stop()

            self._ui_after(finish)

        threading.Thread(target=worker, name="wakesync-update-download", daemon=True).start()

    # ------------------------------------------------------------------
    # Alarm-/snoozescherm (hoogste prioriteit)
    def _ensure_alarm_overlay(self) -> None:
        try:
            state = str(self._runtime.ctx.core.state.value)
        except Exception:
            state = "sleeping"
        active = state in {"ringing", "snoozed"}

        if not active:
            if self._alarm_overlay is not None:
                try:
                    self._alarm_overlay.destroy()
                except Exception:
                    pass
                self._alarm_overlay = None
            return

        if self._sleeping:
            self._wake_from_sleep()
        if self._qr_overlay is not None:
            self._close_qr_overlay()
        if self._update_overlay is not None:
            self._close_update_overlay()
        if self._settings_overlay is not None:
            self._close_settings_section()

        if self._alarm_overlay is None:
            tk = self._tk()
            overlay = tk.Frame(self._root, bg="#190b12")
            overlay.place(x=0, y=0, relwidth=1, relheight=1)
            overlay.lift()
            self._alarm_overlay = overlay

            title = tk.Label(
                overlay, text="", font=("DejaVu Sans", 34, "bold"),
                fg="#ffffff", bg="#190b12",
            )
            title.pack(pady=(58, 8))
            clock = tk.Label(
                overlay, text="", font=("DejaVu Sans", 56, "bold"),
                fg="#ffcc66", bg="#190b12",
            )
            clock.pack()
            sub = tk.Label(
                overlay, text="", font=("DejaVu Sans", 14, "bold"),
                fg="#f2bac3", bg="#190b12",
            )
            sub.pack(pady=(4, 18))
            snooze = tk.Button(
                overlay, text="", font=("DejaVu Sans", 18, "bold"),
                fg="#172033", bg="#ffcc66", activebackground="#ffe19a",
                bd=0, padx=28, pady=12, command=self._snooze_from_screen,
            )
            snooze.pack()
            hint = tk.Label(
                overlay, text="Stoppen: gebruik de fysieke knop op WakeSync",
                font=("DejaVu Sans", 11), fg="#d49aa5", bg="#190b12",
            )
            hint.pack(side="bottom", pady=(0, 30))
            self._widgets.update({
                "_overlay_alarm_title": title,
                "_overlay_alarm_clock": clock,
                "_overlay_alarm_sub": sub,
                "_overlay_alarm_snooze": snooze,
            })

        self._refresh_alarm_overlay(state)

    def _refresh_alarm_overlay(self, state: str) -> None:
        now = self._runtime.ctx.clock.now()
        title = self._widgets.get("_overlay_alarm_title")
        clock = self._widgets.get("_overlay_alarm_clock")
        sub = self._widgets.get("_overlay_alarm_sub")
        snooze = self._widgets.get("_overlay_alarm_snooze")
        if not all((title, clock, sub, snooze)):
            return
        self._set_text(clock, format_time(now, self._runtime.ctx.settings.locale.time_format))
        if state == "ringing":
            self._set_text(title, "Alarm gaat af")
            self._set_text(sub, "Sta op · lamp en geluid volgen je ingestelde alarmprofiel")
            self._set_text(
                snooze, f"Snooze {self._runtime.ctx.settings.alarm.snooze_minutes} minuten"
            )
            snooze.config(state="normal")
        else:
            until = self._runtime.ctx.core.snooze_until
            remaining = max(0, int((until - now).total_seconds())) if until else 0
            minutes, seconds = divmod(remaining, 60)
            self._set_text(title, "Snooze")
            self._set_text(sub, f"Alarm gaat opnieuw af over {minutes:02d}:{seconds:02d}")
            self._set_text(snooze, "Snooze actief")
            snooze.config(state="disabled")

    def _snooze_from_screen(self) -> None:
        try:
            if not self._runtime.ctx.core.snooze():
                self._show_toast("Snooze kon niet worden gestart", error=True)
        except Exception as exc:
            self._show_toast(f"Snooze-fout: {exc}", error=True)

    # ------------------------------------------------------------------
    # Slaapmodus
    def _on_user_activity(self, _event: Any = None) -> str | None:
        self._last_activity = time.monotonic()
        if self._sleeping:
            self._wake_from_sleep()
            return "break"
        return None

    def _sleep_delay(self) -> int:
        try:
            return int(self._runtime.ctx.settings.display.sleep_after_seconds)
        except Exception:
            return 0

    def _maybe_update_sleep_mode(self) -> None:
        if any((
            self._update_overlay is not None,
            self._qr_overlay is not None,
            self._settings_overlay is not None,
            self._alarm_overlay is not None,
        )):
            self._last_activity = time.monotonic()
            if self._sleeping:
                self._wake_from_sleep()
            return
        delay = self._sleep_delay()
        if delay <= 0:
            if self._sleeping:
                self._wake_from_sleep()
            return
        if not self._sleeping and time.monotonic() - self._last_activity >= delay:
            self._enter_sleep_mode()
        elif self._sleeping:
            self._refresh_sleep_content()

    @staticmethod
    def _blend_hex(background: str, foreground: str, amount: float) -> str:
        """Meng twee #RRGGBB-kleuren zonder transparante Tk-canvas-trucs."""
        amount = max(0.0, min(1.0, float(amount)))
        bg = background.lstrip("#")
        fg = foreground.lstrip("#")
        try:
            br, bgc, bb = (int(bg[i:i+2], 16) for i in (0, 2, 4))
            fr, fgc, fb = (int(fg[i:i+2], 16) for i in (0, 2, 4))
        except Exception:
            return foreground
        r = round(br + (fr - br) * amount)
        g = round(bgc + (fgc - bgc) * amount)
        b = round(bb + (fb - bb) * amount)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _enter_sleep_mode(self) -> None:
        if self._sleeping:
            return
        self._sleeping = True
        self._sleep_phase = 0.0
        tk = self._tk()
        overlay = tk.Frame(self._root, bg="#030712")
        overlay.place(x=0, y=0, relwidth=1, relheight=1)
        overlay.lift()
        self._sleep_overlay = overlay

        canvas = tk.Canvas(
            overlay,
            width=SCREEN_WIDTH,
            height=SCREEN_HEIGHT,
            bg="#030712",
            highlightthickness=0,
            bd=0,
        )
        canvas.pack(fill="both", expand=True)
        canvas.bind("<Button-1>", self._on_user_activity)
        self._widgets["_overlay_sleep_canvas"] = canvas

        # Goedgekeurd C9-logo. Op donkere schermen gebruiken we de variant
        # met witte 'WAKE'-letters en behouden we de blauwe SYNC-accenten.
        photo = self._brand_photo((340, 132))
        if photo is not None:
            canvas.create_image(
                SCREEN_WIDTH / 2,
                148,
                image=photo,
                anchor="center",
                tags=("sleep_content", "sleep_logo"),
            )
            self._widgets["_overlay_sleep_logo"] = photo
        else:
            canvas.create_text(
                SCREEN_WIDTH / 2,
                148,
                text="WAKE\nSYNC",
                justify="center",
                fill="#f8fafc",
                font=("DejaVu Sans", 30, "bold"),
                tags=("sleep_content",),
            )

        canvas.create_text(
            SCREEN_WIDTH / 2,
            302,
            text="",
            fill="#f8fafc",
            font=("DejaVu Sans", 52, "bold"),
            tags=("sleep_content", "sleep_time"),
        )
        canvas.create_text(
            SCREEN_WIDTH / 2,
            361,
            text="",
            fill="#8ea2bd",
            font=("DejaVu Sans", 14),
            tags=("sleep_content", "sleep_date"),
        )
        canvas.create_text(
            SCREEN_WIDTH / 2,
            453,
            text="Tik om WakeSync te openen",
            fill="#526176",
            font=("DejaVu Sans", 9),
            tags=("sleep_content",),
        )
        self._refresh_sleep_content()
        self._animate_sleep_glow()

    def _animate_sleep_glow(self) -> None:
        if not self._sleeping:
            self._sleep_animation_job = None
            return
        canvas = self._widgets.get("_overlay_sleep_canvas")
        if canvas is None:
            self._sleep_animation_job = None
            return

        settings = self._runtime.ctx.settings.display
        effect = str(getattr(settings, "sleep_effect", "soft_glow"))
        intensity = max(0, min(100, int(getattr(settings, "sleep_glow_intensity", 65))))
        canvas.delete("sleep_glow")
        self._sleep_phase = (self._sleep_phase + 0.075) % (2 * math.pi)

        if effect != "off" and intensity > 0:
            strength = intensity / 100.0
            cx, cy = SCREEN_WIDTH / 2, 154
            if effect == "soft_glow":
                pulse = 0.86 + 0.14 * (math.sin(self._sleep_phase) + 1) / 2
                specs = [
                    (190, "#1677ff", 0.20),
                    (145, "#22d3ee", 0.13),
                    (108, "#1677ff", 0.09),
                ]
                for radius, color, alpha in specs:
                    mixed = self._blend_hex("#030712", color, alpha * strength * pulse)
                    canvas.create_oval(
                        cx-radius, cy-radius*0.62, cx+radius, cy+radius*0.62,
                        fill=mixed, outline="", tags=("sleep_glow",)
                    )
            elif effect == "pulse_glow":
                pulse = (math.sin(self._sleep_phase * 1.45) + 1) / 2
                radius = 125 + 48 * pulse
                for step, color in enumerate(("#1677ff", "#22d3ee", "#4f8cff")):
                    r = radius + step * 34
                    alpha = (0.20 - step * 0.045) * strength * (0.55 + 0.45 * pulse)
                    mixed = self._blend_hex("#030712", color, alpha)
                    canvas.create_oval(
                        cx-r, cy-r*0.58, cx+r, cy+r*0.58,
                        fill=mixed, outline="", tags=("sleep_glow",)
                    )
            elif effect == "aurora":
                offsets = (
                    (-105, -5, "#1677ff", 178, 92),
                    (105, 8, "#22d3ee", 170, 88),
                    (-30, 42, "#6d5dfc", 142, 74),
                )
                sway = math.sin(self._sleep_phase) * 24
                for index, (ox, oy, color, rx, ry) in enumerate(offsets):
                    x = cx + ox + sway * (1 if index % 2 == 0 else -0.7)
                    y = cy + oy + math.cos(self._sleep_phase + index) * 8
                    alpha = (0.15 - index * 0.018) * strength
                    mixed = self._blend_hex("#030712", color, alpha)
                    canvas.create_oval(
                        x-rx, y-ry, x+rx, y+ry,
                        fill=mixed, outline="", tags=("sleep_glow",)
                    )
            try:
                canvas.tag_lower("sleep_glow")
            except Exception:
                pass

        # Rustig genoeg voor een Pi 5 en vloeiend genoeg voor het 5-inch scherm.
        try:
            self._sleep_animation_job = self._root.after(80, self._animate_sleep_glow)
        except Exception:
            self._sleep_animation_job = None

    def _refresh_sleep_content(self) -> None:
        if not self._sleeping:
            return
        settings = self._runtime.ctx.settings
        now = self._runtime.ctx.clock.now()
        view = settings.display.sleep_view
        canvas = self._widgets.get("_overlay_sleep_canvas")
        if canvas is None:
            return
        show_time = view in {"logo_time", "logo_time_date"}
        show_date = view == "logo_time_date"
        canvas.itemconfigure(
            "sleep_time",
            text=format_time(now, settings.locale.time_format) if show_time else "",
            state=("normal" if show_time else "hidden"),
        )
        canvas.itemconfigure(
            "sleep_date",
            text=(
                f"{DUTCH_WEEKDAYS[now.weekday()]} {now.day} {DUTCH_MONTHS[now.month]}"
                if show_date else ""
            ),
            state=("normal" if show_date else "hidden"),
        )

    def _wake_from_sleep(self) -> None:
        self._last_activity = time.monotonic()
        self._sleeping = False
        if self._sleep_animation_job is not None:
            try:
                self._root.after_cancel(self._sleep_animation_job)
            except Exception:
                pass
            self._sleep_animation_job = None
        overlay = self._sleep_overlay
        self._sleep_overlay = None
        if overlay is not None:
            try:
                overlay.destroy()
            except Exception:
                pass
        for key in (
            "_overlay_sleep_canvas",
            "_overlay_sleep_logo",
        ):
            self._widgets.pop(key, None)

    # ------------------------------------------------------------------
    # Navigatie / tick
    def _render_nav(self) -> None:
        tk = self._tk()
        bar = tk.Frame(self._frame, bg=BG)
        bar.pack(side="bottom", fill="x", padx=24, pady=(4, 8))
        for screen, label in (
            (ScreenId.MAIN, "Vandaag"),
            (ScreenId.AGENDA, "Agenda"),
            (ScreenId.ALARM, "Alarm"),
            (ScreenId.SETTINGS, "Instellingen"),
        ):
            active = self._nav.current is screen
            tk.Button(
                bar, text=label, font=("DejaVu Sans", 10, "bold"),
                fg=TEXT if active else MUTED,
                bg=ACCENT_DARK if active else CARD,
                activebackground=ACCENT, activeforeground=TEXT,
                bd=0, padx=16, pady=8,
                command=lambda target=screen: self._go(target.value),
            ).pack(side="left", expand=True, fill="x", padx=3)

    def _go(self, target: str) -> None:
        self._close_settings_section()
        self._nav.go(ScreenId(target))
        self.render()

    def tick(self) -> None:
        if not self._running:
            return
        try:
            from wekker.main import run_once
            run_once(self._runtime)
            self.render()
            self._ensure_alarm_overlay()
            self._maybe_update_sleep_mode()
        except Exception:
            log.exception("GUI-tick faalde")
        finally:
            try:
                self._root.after(REFRESH_MS, self.tick)
            except Exception:
                self._running = False

    def stop(self) -> None:
        self._running = False
        try:
            self._root.destroy()
        except Exception:
            pass


def _show_startup_splash(root: Any) -> None:
    try:
        import tkinter as tk
        from PIL import Image, ImageTk
        splash = tk.Frame(root, bg="#07111f")
        splash.place(x=0, y=0, relwidth=1, relheight=1)

        logo_path = Path(__file__).resolve().parents[1] / "assets" / "wakesync-logo-dark.png"
        image = Image.open(logo_path).convert("RGBA")
        image.thumbnail((360, 150), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(image)
        logo = tk.Label(splash, image=photo, bg="#07111f", bd=0)
        logo.image = photo
        logo.pack(pady=(115, 0))

        tk.Label(
            splash, text="WakeSync v9 starten…", font=("DejaVu Sans", 11, "bold"),
            fg="#8ea2bd", bg="#07111f",
        ).pack(pady=(16, 0))
        tk.Label(
            splash, text="Klok • agenda • alarm • online beheer",
            font=("DejaVu Sans", 9), fg="#526176", bg="#07111f",
        ).pack(pady=(7, 0))
        root.update_idletasks()
        root.update()
        time.sleep(0.18)
        splash.destroy()
    except Exception:
        return


def launch_gui(runtime: Any, fullscreen: bool = True) -> None:
    try:
        import tkinter as tk
    except ImportError as exc:
        raise SystemExit("tkinter ontbreekt; installeer python3-tk.") from exc
    try:
        root = tk.Tk()
    except Exception as exc:
        raise SystemExit(f"Geen beeldscherm beschikbaar voor de GUI: {exc}") from exc

    if fullscreen:
        root.overrideredirect(True)
        root.geometry(f"{SCREEN_WIDTH}x{SCREEN_HEIGHT}+0+0")
        root.attributes("-fullscreen", True)
        root.attributes("-topmost", True)
        try:
            root.focus_force()
        except Exception:
            pass
    else:
        root.attributes("-fullscreen", False)
        root.geometry(f"{SCREEN_WIDTH}x{SCREEN_HEIGHT}")

    _show_startup_splash(root)
    app = TouchApp(root, runtime)
    root.bind("<Escape>", lambda _e: app.stop())
    root.bind(
        "<F11>",
        lambda _e: root.attributes(
            "-fullscreen", not bool(root.attributes("-fullscreen"))
        ),
    )
    app.tick()
    try:
        root.mainloop()
    finally:
        app.stop()
