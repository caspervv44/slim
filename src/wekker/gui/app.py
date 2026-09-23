"""Fullscreen touchscreen-app (800x480) voor de Raspberry Pi.

De lokale UI bevat alleen dagelijkse wekkerfuncties: klok, agenda en eenvoudige
weergave-instellingen. MyX-koppeling en beheer horen uitsluitend in de webapp
op poort 8080.
"""

from __future__ import annotations

from datetime import date, timedelta
import logging
from typing import Any

from wekker.gui.screens import (
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    GuiData,
    Navigator,
    ScreenId,
    SettingsScreenData,
    build_agenda_data,
    build_main_data,
    format_day_label,
    layout_for,
)

log = logging.getLogger(__name__)
REFRESH_MS = 1000

# Rustig donker ontwerp met voldoende contrast voor een nachtkastje.
BG = "#08111f"
CARD = "#101c2e"
CARD_ALT = "#132239"
TEXT = "#f8fafc"
MUTED = "#8ea2bd"
ACCENT = "#4f8cff"
ACCENT_DARK = "#2f63bd"
BORDER = "#1e3049"
SUCCESS = "#55d6a3"

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


def build_gui_data(runtime: Any, agenda_day: date | None = None) -> GuiData:
    """Maak één consistente momentopname uit de Runtime."""
    from wekker.agenda.providers import get_provider_info

    ctx = runtime.ctx
    now = ctx.clock.now()
    agenda_day = agenda_day or now.date()
    try:
        provider_name = get_provider_info(ctx.settings.agenda.provider).display_name
    except ValueError:
        provider_name = ctx.settings.agenda.provider

    return GuiData(
        main=build_main_data(
            now,
            ctx.core.next_alarm(now),
            time_format=ctx.settings.locale.time_format,
        ),
        agenda=build_agenda_data(
            ctx.cache.get_day(agenda_day),
            provider_name=provider_name,
            day_label=format_day_label(agenda_day, now.date()),
        ),
        settings=SettingsScreenData(
            timezone=ctx.settings.locale.timezone,
            time_format=ctx.settings.locale.time_format,
            region=ctx.settings.locale.region,
            provider=ctx.settings.agenda.provider,
            **_cloud_screen_kwargs(ctx),
        ),
    )


def _cloud_screen_kwargs(ctx: Any) -> dict[str, Any]:
    """Lees alleen reeds bekende cloudstatus; voer hier geen netwerkcall uit."""
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
    }


class TouchApp:
    """Rendert de drie touchscreenpagina's naar tkinter."""

    def __init__(self, root: Any, runtime: Any, navigator: Navigator | None = None) -> None:
        self._root = root
        self._runtime = runtime
        self._nav = navigator or Navigator()
        self._running = True
        self._agenda_day: date | None = None

        root.title("WaveSync")
        try:
            root.geometry(f"{SCREEN_WIDTH}x{SCREEN_HEIGHT}")
        except Exception:
            pass

        self._frame = self._make_frame()
        self._screen: str | None = None
        self._widgets: dict[str, Any] = {}
        self.render()

    def _make_frame(self) -> Any:
        tk = self._tk()
        frame = tk.Frame(self._root, bg=BG)
        frame.pack(fill="both", expand=True)
        return frame

    def _tk(self) -> Any:
        import tkinter as tk
        return tk

    def _clear(self) -> None:
        for child in self._frame.winfo_children():
            child.destroy()

    def _data(self) -> GuiData:
        # De gekozen dag blijft staan als de gebruiker tussen pagina's wisselt.
        # De fallback zonder ``ctx`` houdt de pure/headless GUI-tests eenvoudig.
        try:
            today = self._runtime.ctx.clock.now().date()
        except AttributeError:
            return build_gui_data(self._runtime)
        if self._agenda_day is None:
            self._agenda_day = today
        return build_gui_data(self._runtime, self._agenda_day)

    def render(self) -> dict:
        layout = layout_for(self._nav, self._data())
        if layout["screen"] != self._screen:
            self._rebuild(layout)
        elif layout["screen"] == ScreenId.MAIN.value:
            self._update_main(layout)
        elif layout["screen"] == ScreenId.AGENDA.value:
            self._update_agenda(layout)
        else:
            self._update_settings(layout)
        return layout

    def _rebuild(self, layout: dict) -> None:
        self._clear()
        self._widgets = {}
        self._screen = layout["screen"]
        if self._screen == ScreenId.MAIN.value:
            self._build_main(layout)
        elif self._screen == ScreenId.AGENDA.value:
            self._build_agenda(layout)
        else:
            self._build_settings(layout)

    @staticmethod
    def _set_text(widget: Any, text: str) -> None:
        try:
            current = widget.cget("text")
        except Exception:
            current = None
        if current != text:
            widget.config(text=text)

    def _top_title(self, title: str, subtitle: str = "") -> None:
        tk = self._tk()
        top = tk.Frame(self._frame, bg=BG)
        top.pack(fill="x", padx=28, pady=(15, 4))
        tk.Label(
            top, text=title, font=("DejaVu Sans", 24, "bold"),
            fg=TEXT, bg=BG,
        ).pack(side="left")
        if subtitle:
            tk.Label(
                top, text=subtitle, font=("DejaVu Sans", 12),
                fg=MUTED, bg=BG,
            ).pack(side="right", pady=(8, 0))

    # ------------------------------------------------------------------
    # Hoofdscherm
    def _build_main(self, layout: dict) -> None:
        tk = self._tk()
        self._top_title("WaveSync")

        body = tk.Frame(self._frame, bg=BG)
        body.pack(fill="both", expand=True, padx=28)

        clock_card = tk.Frame(body, bg=CARD)
        clock_card.pack(fill="x", pady=(10, 9))
        time_label = tk.Label(
            clock_card, text=layout["time"],
            font=("DejaVu Sans", 92, "bold"), fg=TEXT, bg=CARD,
        )
        time_label.pack(pady=(16, 6))

        alarm_wrap = tk.Frame(clock_card, bg=CARD)
        alarm_wrap.pack(pady=(0, 14))
        tk.Label(
            alarm_wrap, text="VOLGEND ALARM", font=("DejaVu Sans", 11, "bold"),
            fg=MUTED, bg=CARD,
        ).pack(side="left", padx=(0, 12))
        alarm_label = tk.Label(
            alarm_wrap, text=layout["alarm"],
            font=("DejaVu Sans", 20, "bold"), fg=ACCENT, bg=CARD,
        )
        alarm_label.pack(side="left")

        self._widgets["time"] = time_label
        self._widgets["alarm"] = alarm_label
        self._render_nav()

    def _update_main(self, layout: dict) -> None:
        self._set_text(self._widgets["time"], layout["time"])
        self._set_text(self._widgets["alarm"], layout["alarm"])

    # ------------------------------------------------------------------
    # Agenda
    def _build_agenda(self, layout: dict) -> None:
        tk = self._tk()
        self._top_title("Agenda", layout.get("provider", ""))

        selector = tk.Frame(self._frame, bg=BG)
        selector.pack(fill="x", padx=28, pady=(2, 8))
        prev_btn = tk.Button(
            selector, text="‹", font=("DejaVu Sans", 22, "bold"),
            fg=TEXT, bg=CARD, activebackground=CARD_ALT,
            activeforeground=TEXT, bd=0, width=3,
            command=lambda: self._shift_agenda_day(-1),
        )
        prev_btn.pack(side="left")
        day = tk.Button(
            selector, text=layout["day"], font=("DejaVu Sans", 17, "bold"),
            fg=TEXT, bg=BG, activebackground=BG, activeforeground=ACCENT,
            bd=0, command=self._agenda_today,
        )
        day.pack(side="left", expand=True, fill="x")
        next_btn = tk.Button(
            selector, text="›", font=("DejaVu Sans", 22, "bold"),
            fg=TEXT, bg=CARD, activebackground=CARD_ALT,
            activeforeground=TEXT, bd=0, width=3,
            command=lambda: self._shift_agenda_day(1),
        )
        next_btn.pack(side="right")
        self._widgets["day"] = day

        content = tk.Frame(self._frame, bg=BG)
        content.pack(fill="both", expand=True, padx=28)

        if layout["simulated"] and layout["rows"]:
            badge = tk.Label(
                content, text="VOORBEELDDATA", font=("DejaVu Sans", 9, "bold"),
                fg="#102033", bg="#f5c95d", padx=8, pady=3,
            )
            badge.pack(anchor="e", pady=(0, 4))
            self._widgets["badge"] = badge

        if layout["empty_text"]:
            empty_card = tk.Frame(content, bg=CARD)
            empty_card.pack(fill="x", pady=20)
            empty = tk.Label(
                empty_card, text=layout["empty_text"],
                font=("DejaVu Sans", 22, "bold"), fg=MUTED, bg=CARD,
            )
            empty.pack(pady=35)
            self._widgets["empty"] = empty

        row_widgets = []
        for row in layout["rows"]:
            card = tk.Frame(content, bg=CARD_ALT, bd=0)
            card.pack(fill="x", pady=3)

            time_label = tk.Label(
                card, text=f'{row["start"]} – {row["end"]}',
                font=("DejaVu Sans", 16, "bold"), fg=ACCENT, bg=CARD_ALT,
                width=13, anchor="w",
            )
            time_label.pack(side="left", padx=(13, 4), pady=8)

            info = tk.Frame(card, bg=CARD_ALT)
            info.pack(side="left", fill="both", expand=True, pady=6)

            subject = tk.Label(
                info, text=row["subject"], font=("DejaVu Sans", 16, "bold"),
                fg=TEXT, bg=CARD_ALT, anchor="w", justify="left",
            )
            subject.pack(fill="x")

            meta_parts = []
            if row.get("teacher"):
                meta_parts.append(f'Docent: {row["teacher"]}')
            if row.get("room"):
                meta_parts.append(f'Lokaal: {row["room"]}')
            meta = tk.Label(
                info, text="   ·   ".join(meta_parts), font=("DejaVu Sans", 10),
                fg=MUTED, bg=CARD_ALT, anchor="w",
            )
            meta.pack(fill="x")

            room = tk.Label(
                card, text=(f'LOKAAL\n{row["room"]}' if row.get("room") else "LOKAAL\n—"),
                font=("DejaVu Sans", 10, "bold"), fg=TEXT, bg=CARD,
                padx=10, pady=5, justify="center",
            )
            room.pack(side="right", padx=10)

            row_widgets.append({
                "card": card,
                "time": time_label,
                "subject": subject,
                "meta": meta,
                "room": room,
            })

        self._widgets["rows"] = row_widgets
        self._render_nav()

    def _update_agenda(self, layout: dict) -> None:
        rows = self._widgets.get("rows", [])
        if (
            bool(self._widgets.get("badge")) != bool(layout["simulated"] and layout["rows"])
            or bool(self._widgets.get("empty")) != bool(layout["empty_text"])
            or len(rows) != len(layout["rows"])
        ):
            self._rebuild(layout)
            return

        self._set_text(self._widgets["day"], layout["day"])
        if layout["empty_text"]:
            self._set_text(self._widgets["empty"], layout["empty_text"])

        for widgets, row in zip(rows, layout["rows"]):
            self._set_text(widgets["time"], f'{row["start"]} – {row["end"]}')
            self._set_text(widgets["subject"], row["subject"])
            meta_parts = []
            if row.get("teacher"):
                meta_parts.append(f'Docent: {row["teacher"]}')
            if row.get("room"):
                meta_parts.append(f'Lokaal: {row["room"]}')
            self._set_text(widgets["meta"], "   ·   ".join(meta_parts))
            self._set_text(
                widgets["room"],
                f'LOKAAL\n{row["room"]}' if row.get("room") else "LOKAAL\n—",
            )

    def _shift_agenda_day(self, days: int) -> None:
        base = self._agenda_day or self._runtime.ctx.clock.now().date()
        self._agenda_day = base + timedelta(days=days)
        self.render()

    def _agenda_today(self) -> None:
        self._agenda_day = self._runtime.ctx.clock.now().date()
        self.render()

    # ------------------------------------------------------------------
    # Instellingen
    def _build_settings(self, layout: dict) -> None:
        tk = self._tk()
        self._top_title("Instellingen")

        body = tk.Frame(self._frame, bg=BG)
        body.pack(fill="both", expand=True, padx=24, pady=(4, 0))

        left = tk.Frame(body, bg=BG, width=310)
        left.pack(side="left", fill="both", padx=(0, 8))
        left.pack_propagate(False)

        # Tijdzone als echte dropdown. Dit is sneller en duidelijker dan
        # stap voor stap door zones bladeren.
        zone_card = tk.Frame(left, bg=CARD)
        zone_card.pack(fill="x", pady=(0, 8))
        tk.Label(
            zone_card, text="Tijdzone", font=("DejaVu Sans", 14, "bold"),
            fg=TEXT, bg=CARD, anchor="w",
        ).pack(fill="x", padx=14, pady=(11, 3))
        tk.Label(
            zone_card, text="Kies de regio voor datum, tijd en zomertijd.",
            font=("DejaVu Sans", 9), fg=MUTED, bg=CARD, anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 6))

        zone_labels = [label for _value, label in TIMEZONE_CHOICES]
        self._zone_by_label = {label: value for value, label in TIMEZONE_CHOICES}
        zone_var = tk.StringVar(value=self._timezone_label(layout["timezone"]))
        zone_menu = tk.OptionMenu(
            zone_card, zone_var, *zone_labels,
            command=self._select_timezone,
        )
        zone_menu.config(
            font=("DejaVu Sans", 11, "bold"),
            fg=TEXT, bg=CARD_ALT, activebackground=ACCENT_DARK,
            activeforeground=TEXT, bd=0, highlightthickness=0,
            anchor="w", padx=8, pady=7,
        )
        try:
            zone_menu["menu"].config(
                font=("DejaVu Sans", 10), fg=TEXT, bg=CARD_ALT,
                activebackground=ACCENT_DARK, activeforeground=TEXT,
            )
        except Exception:
            pass
        zone_menu.pack(fill="x", padx=12, pady=(0, 11))
        self._widgets["timezone_var"] = zone_var
        self._widgets["timezone_menu"] = zone_menu

        fmt_card = tk.Frame(left, bg=CARD)
        fmt_card.pack(fill="x", pady=(0, 8))
        tk.Label(
            fmt_card, text="Tijdweergave", font=("DejaVu Sans", 14, "bold"),
            fg=TEXT, bg=CARD, anchor="w",
        ).pack(fill="x", padx=14, pady=(11, 3))
        tk.Label(
            fmt_card, text="Tik om te wisselen tussen 24-uurs en AM/PM.",
            font=("DejaVu Sans", 9), fg=MUTED, bg=CARD, anchor="w",
        ).pack(fill="x", padx=14)
        toggle = tk.Button(
            fmt_card, text=self._format_label(layout["time_format"]),
            font=("DejaVu Sans", 12, "bold"), fg=TEXT, bg=ACCENT_DARK,
            activebackground=ACCENT, activeforeground=TEXT,
            bd=0, pady=8, command=self._toggle_time_format,
        )
        toggle.pack(fill="x", padx=12, pady=(7, 11))
        self._widgets["time_format"] = toggle

        tk.Label(
            left,
            text="MyX en roosterkoppeling beheer je via de lokale webapp.",
            font=("DejaVu Sans", 9), fg=MUTED, bg=BG,
            wraplength=292, justify="left",
        ).pack(anchor="w", pady=(3, 0))

        cloud_card = tk.Frame(body, bg=CARD)
        cloud_card.pack(side="right", fill="both", expand=True, padx=(8, 0))
        tk.Label(
            cloud_card, text="Online beheer", font=("DejaVu Sans", 15, "bold"),
            fg=TEXT, bg=CARD, anchor="w",
        ).pack(fill="x", padx=14, pady=(10, 2))

        status = tk.Label(
            cloud_card, text=layout.get("cloud_status", ""),
            font=("DejaVu Sans", 9, "bold"),
            fg=SUCCESS if layout.get("cloud_ready") else MUTED,
            bg=CARD, anchor="w",
        )
        status.pack(fill="x", padx=14)
        self._widgets["cloud_status"] = status

        error = tk.Label(
            cloud_card, text=layout.get("cloud_error", ""),
            font=("DejaVu Sans", 8), fg="#f59e9e", bg=CARD,
            anchor="w", justify="left", wraplength=430,
        )
        error.pack(fill="x", padx=14, pady=(1, 0))
        self._widgets["cloud_error"] = error

        cloud_content = tk.Frame(cloud_card, bg=CARD)
        cloud_content.pack(fill="both", expand=True, padx=12, pady=(5, 8))

        qr_holder = tk.Label(
            cloud_content, text="QR wordt\nvoorbereid…",
            font=("DejaVu Sans", 10, "bold"), fg=MUTED, bg="#ffffff",
            width=15, height=7, justify="center",
        )
        qr_holder.pack(side="left", anchor="n", padx=(0, 12))
        self._widgets["cloud_qr"] = qr_holder

        details = tk.Frame(cloud_content, bg=CARD)
        details.pack(side="left", fill="both", expand=True)

        tk.Label(
            details, text="Scan de QR-code of gebruik de link:",
            font=("DejaVu Sans", 9, "bold"), fg=TEXT, bg=CARD, anchor="w",
        ).pack(fill="x")
        link = tk.Label(
            details, text=layout.get("cloud_url") or "Wordt lokaal aangemaakt…",
            font=("DejaVu Sans", 8), fg=ACCENT, bg=CARD, anchor="w",
            justify="left", wraplength=305,
        )
        link.pack(fill="x", pady=(2, 5))
        self._widgets["cloud_url"] = link

        user = tk.Label(
            details, text=f'Gebruikersnaam: {layout.get("cloud_username", "basis")}',
            font=("DejaVu Sans", 10, "bold"), fg=TEXT, bg=CARD, anchor="w",
        )
        user.pack(fill="x", pady=1)
        self._widgets["cloud_user"] = user

        password = tk.Label(
            details, text=self._cloud_password_text(layout),
            font=("DejaVu Sans Mono", 10, "bold"), fg=TEXT, bg=CARD,
            anchor="w", justify="left",
        )
        password.pack(fill="x", pady=1)
        self._widgets["cloud_password"] = password

        tk.Label(
            details,
            text="De QR en login worden lokaal gemaakt. Een storing op de server "
                 "blokkeert de klok niet; WaveSync probeert automatisch opnieuw.",
            font=("DejaVu Sans", 8), fg=MUTED, bg=CARD,
            anchor="w", justify="left", wraplength=305,
        ).pack(fill="x", pady=(5, 0))

        self._refresh_qr(layout)
        self._render_nav()

    def _update_settings(self, layout: dict) -> None:
        zone_var = self._widgets.get("timezone_var")
        if zone_var is not None:
            try:
                wanted = self._timezone_label(layout["timezone"])
                if zone_var.get() != wanted:
                    zone_var.set(wanted)
            except Exception:
                pass
        self._set_text(self._widgets["time_format"], self._format_label(layout["time_format"]))
        self._set_text(self._widgets["cloud_status"], layout.get("cloud_status", ""))
        self._set_text(self._widgets["cloud_error"], layout.get("cloud_error", ""))
        self._set_text(
            self._widgets["cloud_url"],
            layout.get("cloud_url") or "Wordt lokaal aangemaakt…",
        )
        self._set_text(
            self._widgets["cloud_user"],
            f'Gebruikersnaam: {layout.get("cloud_username", "basis")}',
        )
        self._set_text(
            self._widgets["cloud_password"],
            self._cloud_password_text(layout),
        )
        if self._widgets.get("_qr_url") != layout.get("cloud_url"):
            self._refresh_qr(layout)

    @staticmethod
    def _cloud_password_text(layout: dict) -> str:
        if layout.get("cloud_password_changed"):
            return "Wachtwoord: gewijzigd op de website"
        password = layout.get("cloud_password") or "wordt aangemaakt…"
        return f"Wachtwoord: {password}"

    def _refresh_qr(self, layout: dict) -> None:
        """Maak lokaal een QR-code; de beheer-URL gaat niet naar een derde partij."""
        widget = self._widgets.get("cloud_qr")
        url = layout.get("cloud_url") or ""
        self._widgets["_qr_url"] = url
        if widget is None or not url:
            return
        try:
            import qrcode
            from PIL import ImageTk

            image = qrcode.make(url)
            image = image.resize((118, 118))
            photo = ImageTk.PhotoImage(image)
            widget.config(image=photo, text="", width=118, height=118)
            # Tk bewaart zelf geen Python-reference naar PhotoImage.
            self._widgets["_qr_photo"] = photo
        except Exception as exc:
            log.warning("QR-code kon niet worden getekend: %s", exc)
            widget.config(
                image="", text="QR niet\nbeschikbaar",
                width=15, height=7,
            )

    @staticmethod
    def _timezone_label(zone: str) -> str:
        return dict(TIMEZONE_CHOICES).get(zone, zone)

    @staticmethod
    def _format_label(value: str) -> str:
        return "24 uur · 20:41" if value == "24h" else "12 uur · 8:41 PM"

    def _select_timezone(self, label: str) -> None:
        zone = getattr(self, "_zone_by_label", {}).get(label)
        if zone:
            self._save_locale(timezone=zone)

    def _toggle_time_format(self) -> None:
        current = self._runtime.ctx.settings.locale.time_format
        self._save_locale(time_format="12h" if current == "24h" else "24h")

    def _save_locale(
        self,
        *,
        timezone: str | None = None,
        time_format: str | None = None,
    ) -> None:
        ctx = self._runtime.ctx
        patch: dict[str, str] = {}
        if timezone is not None:
            patch["timezone"] = timezone
        if time_format is not None:
            patch["time_format"] = time_format

        try:
            nieuwe = ctx.settings.update_from_dict({"locale": patch})
            ctx.settings = nieuwe
            ctx.core.update_settings(nieuwe)
            ctx.display.update_settings(nieuwe)
            ctx.button.update_settings(nieuwe)
            set_timezone = getattr(ctx.clock, "set_timezone", None)
            if callable(set_timezone):
                set_timezone(nieuwe.locale.timezone)
            ctx.store.save(nieuwe.to_dict())
        except Exception:
            log.exception("lokale instellingen opslaan faalde")
            return
        self.render()

    # ------------------------------------------------------------------
    # Onderste navigatie
    def _render_nav(self) -> None:
        tk = self._tk()
        bar = tk.Frame(self._frame, bg=BG)
        bar.pack(side="bottom", fill="x", padx=28, pady=(5, 12))

        items = (
            (ScreenId.MAIN, "Klok"),
            (ScreenId.AGENDA, "Agenda"),
            (ScreenId.SETTINGS, "Instellingen"),
        )
        for screen, label in items:
            active = self._nav.current is screen
            btn = tk.Button(
                bar, text=label, font=("DejaVu Sans", 12, "bold"),
                fg=TEXT if active else MUTED,
                bg=ACCENT_DARK if active else CARD,
                activebackground=ACCENT,
                activeforeground=TEXT,
                bd=0, padx=18, pady=8,
                command=lambda target=screen: self._go(target.value),
            )
            btn.pack(side="left", expand=True, fill="x", padx=3)

    def _go(self, target: str) -> None:
        self._nav.go(ScreenId(target))
        self.render()

    def tick(self) -> None:
        if not self._running:
            return
        try:
            from wekker.main import run_once
            run_once(self._runtime)
            self.render()
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


def launch_gui(runtime: Any, fullscreen: bool = True) -> None:
    """Start de touchscreen-GUI."""
    try:
        import tkinter as tk
    except ImportError as exc:
        raise SystemExit(
            "tkinter ontbreekt; installeer python3-tk (apt) voor de GUI."
        ) from exc
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
