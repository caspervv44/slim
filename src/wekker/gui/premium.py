"""WakeSync Premium Touch UI.

Gebruikt de bestaande WakeSync-gegevens, alarmacties, opslag, updater en overlays.
Alleen de vier hoofdschermen worden grafisch opnieuw getekend.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import logging

from PIL import ImageTk

from wekker.gui import app as legacy
from wekker.gui.premium_render import (
    HitTarget, PALETTES, THEME_TITLES, render_screen,
)

log = logging.getLogger(__name__)

# Bestaande interne codes blijven intact: oude instellingen en cloudpatches
# zijn dus compatibel met de rijkere themanamen.
legacy.THEME_CHOICES = tuple(THEME_TITLES.items())
for theme_id, pal in PALETTES.items():
    if theme_id in legacy.THEMES:
        legacy.THEMES[theme_id].update({
            "bg": pal.bg,
            "card": pal.card,
            "card_alt": pal.raised,
            "text": pal.text,
            "muted": pal.muted,
            "accent": pal.accent,
            "accent_dark": pal.raised,
            "border": pal.border,
            "success": pal.success,
        })


class PremiumTouchApp(legacy.TouchApp):
    """Visuele uitbreiding; alle businesslogica blijft in de basisklasse."""

    def __init__(self, root: Any, runtime: Any, navigator: Any = None) -> None:
        self._premium_hits: list[HitTarget] = []
        self._premium_details_overlay: Any | None = None
        try:
            super().__init__(root, runtime, navigator)
        except TypeError:
            # Val terug op 2-arg basis (bv. StubApp in test_gui_kiosk die
            # via monkeypatch als basis wordt gebonden bij lazy import).
            super().__init__(root, runtime)  # type: ignore[misc]

    def _premium_draw(self, layout: dict) -> None:
        import tkinter as tk

        canvas = self._widgets.get("_premium_canvas")
        if canvas is None or not canvas.winfo_exists():
            canvas = tk.Canvas(
                self._frame, width=800, height=480,
                bg=legacy.BG, highlightthickness=0, bd=0, cursor="hand2",
            )
            canvas.pack(fill="both", expand=True)
            canvas.bind("<Button-1>", self._premium_click)
            self._widgets["_premium_canvas"] = canvas

        # De originele C9-logopixels komen rechtstreeks uit de bestaande repo.
        # Ze worden nooit vervangen of ingekleurd door een thema.
        assets_dir = Path(__file__).resolve().parents[1] / "assets"
        logo_path = assets_dir / "wakesync-logo.png"
        try:
            now = self._runtime.ctx.clock.now()
        except AttributeError:
            from datetime import datetime
            now = datetime.now()

        # Het Alarm-model bevat de ingestelde primaire alarmtijd, niet de
        # huidige systeemtijd. Daarom geven we de echte kloktijd apart door.
        if layout.get("screen") == "alarm":
            formaat=self._runtime.ctx.settings.locale.time_format
            layout={**layout,"_clock_time": legacy.format_time(now,formaat)}
        image, hits = render_screen(
            layout,
            theme=self._active_theme,
            now=now,
            asset_dir=assets_dir,
            logo_path=logo_path,
            selected_alarm_id=self._alarm_selected_id,
            alarm_list_page=self._alarm_list_page,
        )
        photo = ImageTk.PhotoImage(image, master=self._root)
        canvas.delete("all")
        canvas.create_image(0, 0, image=photo, anchor="nw")
        self._widgets["_premium_photo"] = photo
        self._premium_hits = hits

    # Alle pagina's krijgen dezelfde nieuwe navigatie, kleuren en grafische kaartstijl.
    def _build_main(self, layout: dict) -> None:
        self._premium_draw(layout)

    def _update_main(self, layout: dict) -> None:
        self._premium_draw(layout)

    def _build_agenda(self, layout: dict) -> None:
        self._premium_draw(layout)

    def _update_agenda(self, layout: dict) -> None:
        self._premium_draw(layout)

    def _build_alarm_screen(self, layout: dict) -> None:
        self._premium_draw(layout)

    def _update_alarm_screen(self, layout: dict) -> None:
        self._premium_draw(layout)

    def _build_settings(self, layout: dict) -> None:
        self._premium_draw(layout)

    def _update_settings(self, layout: dict) -> None:
        self._premium_draw(layout)
        # Bestaand webbeheer blijft live status tonen in het originele overlay.
        if self._settings_overlay is not None and self._settings_section == "cloud":
            self._update_cloud_section(layout)

    def _premium_click(self, event: Any) -> str:
        x, y = int(event.x), int(event.y)
        chosen = next(
            (hit for hit in reversed(self._premium_hits) if hit.contains(x, y)),
            None,
        )
        if chosen is None:
            return "break"
        action, payload = chosen.action, chosen.payload
        try:
            if action == "nav":
                self._go(payload)
            elif action == "agenda-day":
                self._shift_agenda_day(int(payload))
            elif action == "agenda-today":
                self._agenda_today()
            elif action == "agenda-row":
                rows = self._data().agenda.rows
                index = int(payload)
                if 0 <= index < len(rows):
                    row = rows[index]
                    details = " · ".join(
                        part for part in (
                            row.subject,
                            f"Lokaal {row.room}" if row.room else "",
                            row.teacher,
                        ) if part
                    )
                    self._show_toast(details[:88])
            elif action == "agenda-page":
                self._shift_agenda_page(int(payload))
            elif action == "alarm-page":
                self._change_alarm_page(int(payload))
            elif action == "new-alarm":
                self._show_alarm_creator()
            elif action == "select-alarm":
                self._premium_show_alarm_details(payload)
            elif action == "toggle-alarm":
                self._toggle_alarm_profile(payload)
            elif action == "toggle-speaker":
                self._toggle_alarm_profile_bool(payload, "speaker_enabled")
            elif action == "toggle-lamp":
                self._toggle_alarm_profile_bool(payload, "lamp_blink")
            elif action == "cycle-snooze":
                self._cycle_alarm_profile_value(
                    payload, "snooze_minutes", [5, 9, 10, 15, 20, 30]
                )
            elif action == "theme":
                self._save_display_patch({"theme": payload})
            elif action == "display":
                self._show_settings_section("display")
            elif action == "cloud":
                self._show_settings_section("cloud")
            elif action == "time-format":
                self._toggle_time_format()
            elif action == "settings":
                if payload == "software":
                    self._show_update_overlay()
                elif payload == "diagnostics":
                    self._show_settings_section("diagnostics")
        except Exception as exc:
            log.exception("Premium-touchactie '%s' faalde", action)
            self._show_toast(f"Actie mislukt: {exc}", error=True)
        return "break"

    def _premium_close_details(self) -> None:
        overlay = self._premium_details_overlay
        self._premium_details_overlay = None
        if overlay is not None:
            try:
                overlay.destroy()
            except Exception:
                log.exception("Alarmdetails sluiten mislukt")

    def _premium_show_alarm_details(self, alarm_id: str) -> None:
        """Open het bestaande volledige alarminstellingenpaneel bij een alarmkaart.

        Hierdoor blijven ook volume, lampsterkte, patroon en verwijderen bereikbaar,
        zelfs wanneer ze niet allemaal op de compacte hoofdkaart passen.
        """
        import tkinter as tk

        current = self._alarm_item(alarm_id)
        if current is None:
            return
        self._premium_close_details()
        self._select_alarm(alarm_id)
        palette = PALETTES.get(self._active_theme, PALETTES["midnight"])
        overlay = tk.Frame(self._root, bg=palette.bg)
        overlay.place(x=0,y=0,width=800,height=480)
        overlay.lift()
        self._premium_details_overlay = overlay
        heading = tk.Frame(overlay,bg=palette.bg)
        heading.pack(fill="x",padx=26,pady=(10,3))
        tk.Label(
            heading,text="Alarm aanpassen",
            font=("DejaVu Sans",18,"bold"),
            fg=palette.text,bg=palette.bg,
        ).pack(side="left",padx=6)
        tk.Button(
            heading,text="✕ Sluiten",
            font=("DejaVu Sans",11,"bold"),bd=0,
            fg=palette.text,bg=palette.raised,
            activebackground=palette.card,activeforeground=palette.text,
            padx=15,pady=7,command=self._premium_close_details,
        ).pack(side="right")
        panel = tk.Frame(overlay,bg=palette.card)
        panel.pack(fill="both",expand=True,padx=110,pady=(3,9))
        # We hergebruiken de oorspronkelijke configuratiefunctie.
        self._build_alarm_config_panel(panel,current)

    def _save_alarm_profile_patch(
        self, alarm_id: str, patch: dict[str, Any], *, toast: str = "Alarm opgeslagen"
    ) -> bool:
        result = super()._save_alarm_profile_patch(alarm_id,patch,toast=toast)
        if result:
            self._premium_close_details()
        return result

    def _delete_alarm_profile(self, alarm_id: str) -> None:
        super()._delete_alarm_profile(alarm_id)
        self._premium_close_details()
