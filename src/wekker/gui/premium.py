"""WakeSync Premium v10.2.2: vier thema's, detailschermen en rustige slaapstand.

De bestaande TouchApp blijft verantwoordelijk voor gegevens, acties en alarms.
De premium-laag verandert uitsluitend de weergave; een Canvas blijft bestaan bij
tabwissels zodat er geen leeg frame tussendoor verschijnt.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageEnhance, ImageTk

from wekker.gui import app as legacy
from wekker.gui.premium_render import (
    HitTarget,
    PALETTES,
    THEME_TITLES,
    render_detail_screen,
    render_screen,
    render_sleep_screen,
)

log = logging.getLogger(__name__)

# Bestaande opgeslagen thema-ID's blijven hetzelfde.
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


def volgende_waarde(huidig: Any, keuzes: list[Any] | tuple[Any, ...]) -> Any:
    """Cyclische keuze, ook wanneer oude instellingen een onbekende waarde hebben."""
    if not keuzes:
        raise ValueError("Geen keuzes ingesteld")
    try:
        index = keuzes.index(huidig)
    except ValueError:
        index = -1
    return keuzes[(index + 1) % len(keuzes)]


class PremiumTouchApp(legacy.TouchApp):
    """Vernieuwde interface met behoud van de bestaande wekkerfuncties."""

    def __init__(self, root: Any, runtime: Any, navigator: Any = None) -> None:
        self._premium_hits: list[HitTarget] = []
        self._premium_details_overlay: Any | None = None
        self._premium_detail_canvas: Any | None = None
        self._premium_detail_photo: Any | None = None
        self._premium_detail_item: int | None = None
        self._premium_detail_hits: list[HitTarget] = []
        self._premium_detail_kind: str | None = None
        self._premium_canvas_item: int | None = None
        self._premium_render_key: str | None = None
        self._premium_last_layout: dict[str, Any] | None = None
        self._premium_creator_photo: Any | None = None
        self._premium_creator_theme: str | None = None
        self._premium_sleep_photo: Any | None = None
        self._premium_test_token = 0
        try:
            super().__init__(root, runtime, navigator)
        except TypeError:
            # Val terug op 2-arg basis (bv. StubApp in test_gui_kiosk die
            # via monkeypatch als basis wordt gebonden bij lazy import).
            super().__init__(root, runtime)  # type: ignore[misc]
        # Een tweede start via de snelkoppeling vraagt dit venster naar voren.
        # Geen kalibratiematrix of aangepaste touchcoördinaten in de applicatie.
        self._premium_focus_file = os.environ.get("WAKESYNC_FOCUS_FILE", "")
        self._premium_focus_seen = 0
        if self._premium_focus_file:
            self._root.after(700, self._premium_poll_focus)

    @property
    def _premium_assets(self) -> Path:
        return Path(__file__).resolve().parents[1] / "assets"

    def _premium_now(self) -> Any:
        try:
            return self._runtime.ctx.clock.now()
        except AttributeError:
            from datetime import datetime
            return datetime.now()

    def _rebuild(self, layout: dict) -> None:
        """Behoud dezelfde Canvas bij een tabwissel, zonder de oude _clear()."""
        self._screen = layout["screen"]
        self._premium_draw(layout)

    def _premium_draw(self, layout: dict) -> None:
        import tkinter as tk

        canvas = self._widgets.get("_premium_canvas")
        if canvas is None or not canvas.winfo_exists():
            canvas = tk.Canvas(
                self._frame, width=800, height=480,
                bg=PALETTES.get(self._active_theme, PALETTES["midnight"]).bg,
                highlightthickness=0, bd=0, cursor="hand2",
            )
            canvas.pack(fill="both", expand=True)
            canvas.bind("<Button-1>", self._premium_click)
            self._widgets["_premium_canvas"] = canvas
            self._premium_canvas_item = None
            self._premium_render_key = None

        now = self._premium_now()
        settings = self._runtime.ctx.settings
        if layout.get("screen") == "alarm":
            layout = {**layout, "_clock_time": legacy.format_time(now, settings.locale.time_format)}
        # Geen kostbare, overbodige PIL-render elke seconde: tijd wordt per
        # minuut bijgewerkt, datawijzigingen en schermwissels direct.
        fingerprint = json.dumps(
            {
                "layout": layout,
                "theme": self._active_theme,
                "minute": now.strftime("%Y-%m-%dT%H:%M"),
                "selected": self._alarm_selected_id,
                "page": self._alarm_list_page,
            },
            sort_keys=True, default=str, ensure_ascii=False,
        )
        if fingerprint == self._premium_render_key and self._premium_canvas_item is not None:
            return
        assets = self._premium_assets
        image, hits = render_screen(
            layout, theme=self._active_theme, now=now, asset_dir=assets,
            logo_path=assets / "wakesync-logo.png",
            selected_alarm_id=self._alarm_selected_id,
            alarm_list_page=self._alarm_list_page,
        )
        photo = ImageTk.PhotoImage(image, master=self._root)
        # De nieuwe foto is al volledig klaar voordat hij in één keer verschijnt.
        if self._premium_canvas_item is None:
            self._premium_canvas_item = canvas.create_image(
                0, 0, image=photo, anchor="nw",
            )
        else:
            canvas.itemconfigure(self._premium_canvas_item, image=photo)
        self._widgets["_premium_photo"] = photo
        self._premium_hits = hits
        self._premium_last_layout = layout
        self._premium_render_key = fingerprint

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
        if self._settings_overlay is not None and self._settings_section == "cloud":
            self._update_cloud_section(layout)
    def _premium_click(self, event: Any) -> str:
        chosen = next((
            hit for hit in reversed(self._premium_hits)
            if hit.contains(int(event.x), int(event.y))
        ), None)
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
                    parts = [
                        row.subject,
                        f"Lokaal {row.room}" if row.room else "",
                        row.teacher,
                    ]
                    self._show_toast(" · ".join(x for x in parts if x)[:88])
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
            elif action == "settings" and payload in {"software", "diagnostics"}:
                self._premium_open_system_page(payload)
            elif action in {"software", "diagnostics"}:
                # Ook de vroegere rendereracties worden expliciet ondersteund.
                self._premium_open_system_page(action)
            else:
                log.warning("Onbekende premium-actie: %s", action)
                self._show_toast("Deze actie is niet beschikbaar", error=True)
        except Exception as exc:
            log.exception("Premium-touchactie '%s' faalde", action)
            self._show_toast("Actie kon niet worden uitgevoerd", error=True)
        return "break"

    def _premium_poll_focus(self) -> None:
        """Lees alleen ons eigen focusverzoek; geen signalen naar andere processen."""
        try:
            stamp = Path(self._premium_focus_file).stat().st_mtime_ns
            if stamp > self._premium_focus_seen:
                self._premium_focus_seen = stamp
                if getattr(self, "_sleeping", False):
                    self._wake_from_sleep()
                self._root.deiconify()
                self._root.lift()
                self._root.focus_force()
        except FileNotFoundError:
            pass
        except Exception:
            log.debug("Venster activeren niet beschikbaar", exc_info=True)
        try:
            self._root.after(700, self._premium_poll_focus)
        except Exception:
            pass  # Het hoofdvenster is afgesloten.

    def _premium_open_system_page(self, section: str) -> None:
        """Gebruik een tijdens installatie gecontroleerde bestaande schermfunctie.

        De update-installer leest de echte TouchApp op de gebruiker zijn clone.
        Zo wordt geen updater vervangen en wordt geen nieuwe updateactie verzonnen.
        """
        from wekker.gui.settings_routes_v1021 import ROUTES
        route = ROUTES[section]
        name = route["method"]
        if not name.startswith(("_show_", "_open_")):
            raise ValueError("Ongeldige systeemschermfunctie")
        callback = getattr(self, name, None)
        if not callable(callback):
            raise RuntimeError("Systeemscherm ontbreekt; voer de 10.2.1-installer opnieuw uit")
        self._premium_close_details()
        self._last_activity = time.monotonic()
        callback(*route["args"])

    def _premium_close_details(self) -> None:
        overlay = self._premium_details_overlay
        self._premium_details_overlay = None
        self._premium_detail_canvas = None
        self._premium_detail_item = None
        self._premium_detail_photo = None
        self._premium_detail_kind = None
        self._premium_detail_hits = []
        if overlay is not None:
            try:
                overlay.destroy()
            except Exception:
                log.exception("Detailvenster sluiten mislukt")

    def _premium_open_detail(self, kind: str) -> None:
        import tkinter as tk

        self._premium_close_details()
        pal = PALETTES.get(self._active_theme, PALETTES["midnight"])
        overlay = tk.Frame(self._root, bg=pal.bg)
        overlay.place(x=0, y=0, width=800, height=480)
        overlay.lift()
        canvas = tk.Canvas(
            overlay, width=800, height=480, bg=pal.bg,
            highlightthickness=0, bd=0,
        )
        canvas.pack(fill="both", expand=True)
        canvas.bind("<Button-1>", self._premium_detail_click)
        self._premium_details_overlay = overlay
        self._premium_detail_canvas = canvas
        self._premium_detail_kind = kind
        self._last_activity = time.monotonic()
        self._premium_redraw_detail()

    def _premium_redraw_detail(self) -> None:
        canvas = self._premium_detail_canvas
        if canvas is None or not canvas.winfo_exists():
            return
        kind = self._premium_detail_kind
        if kind == "display":
            item = None
        elif kind == "alarm":
            item = self._alarm_item(self._alarm_selected_id)
            if item is None:
                self._premium_close_details()
                return
        else:
            return
        image, hits = render_detail_screen(
            kind, self._active_theme, self._premium_now(), self._premium_assets,
            settings=self._runtime.ctx.settings, item=item,
        )
        photo = ImageTk.PhotoImage(image, master=self._root)
        if self._premium_detail_item is None:
            self._premium_detail_item = canvas.create_image(
                0, 0, image=photo, anchor="nw",
            )
        else:
            canvas.itemconfigure(self._premium_detail_item, image=photo)
        self._premium_detail_photo = photo
        self._premium_detail_hits = hits

    def _show_settings_section(self, section: str) -> None:
        if section != "display":
            self._premium_close_details()
            super()._show_settings_section(section)
            return
        self._close_settings_section()
        self._settings_section = "display"
        self._premium_open_detail("display")
        # Legacy gebruikt _settings_overlay om automatische slaapmodus te blokkeren.
        self._settings_overlay = self._premium_details_overlay

    def _close_settings_section(self) -> None:
        if self._settings_section == "display":
            self._settings_overlay = None
            self._settings_section = None
            self._premium_close_details()
            return
        super()._close_settings_section()

    def _premium_show_alarm_details(self, alarm_id: str) -> None:
        if self._alarm_item(alarm_id) is None:
            return
        self._select_alarm(alarm_id)
        self._premium_open_detail("alarm")

    def _premium_detail_click(self, event: Any) -> str:
        hit = next((
            target for target in reversed(self._premium_detail_hits)
            if target.contains(int(event.x), int(event.y))
        ), None)
        if hit is None:
            return "break"
        action, value = hit.action, hit.payload
        try:
            if action == "close-detail":
                if self._premium_detail_kind == "display":
                    self._close_settings_section()
                else:
                    self._premium_close_details()
                return "break"
            if action == "preview-sleep":
                self._close_settings_section()
                self._enter_sleep_mode()
                return "break"
            if self._premium_detail_kind == "display":
                self._premium_display_action(action, value)
            elif self._premium_detail_kind == "alarm":
                self._premium_alarm_action(action)
            self._premium_redraw_detail()
        except Exception:
            log.exception("Premium-detailactie %s mislukt", action)
            self._show_toast("Instelling kon niet worden opgeslagen", error=True)
        return "break"

    def _premium_display_action(self, action: str, payload: str) -> None:
        display = self._runtime.ctx.settings.display
        locale = self._runtime.ctx.settings.locale
        if action == "theme":
            self._save_display_patch({"theme": payload})
        elif action == "time-format":
            self._toggle_time_format()
        elif action == "next-timezone":
            zones = [zone for zone, _label in legacy.TIMEZONE_CHOICES]
            self._save_locale(timezone=volgende_waarde(locale.timezone, zones))
        elif action == "next-sleep-after":
            waarden = [waarde for waarde, _label in legacy.SLEEP_AFTER_CHOICES]
            self._save_display_patch({
                "sleep_after_seconds": volgende_waarde(display.sleep_after_seconds, waarden),
            })
        elif action == "next-sleep-view":
            waarden = [waarde for waarde, _label in legacy.SLEEP_VIEW_CHOICES]
            self._save_display_patch({
                "sleep_view": volgende_waarde(display.sleep_view, waarden),
            })
        elif action == "next-sleep-effect":
            waarden = [waarde for waarde, _label in legacy.SLEEP_EFFECT_CHOICES]
            self._save_display_patch({
                "sleep_effect": volgende_waarde(display.sleep_effect, waarden),
            })
        elif action == "next-glow":
            waarden = list(legacy.SLEEP_GLOW_LEVELS)
            huidige = min(waarden, key=lambda x: abs(x - display.sleep_glow_intensity))
            self._save_display_patch({"sleep_glow_intensity": volgende_waarde(huidige, waarden)})
        elif action == "next-brightness":
            self._save_display_patch({"brightness": (int(display.brightness) // 10 * 10 + 10) % 110})

    def _premium_alarm_action(self, action: str) -> None:
        alarm_id = self._alarm_selected_id
        if not alarm_id:
            return
        if action == "alarm-enabled":
            self._toggle_alarm_profile(alarm_id)
        elif action == "alarm-speaker":
            self._toggle_alarm_profile_bool(alarm_id, "speaker_enabled")
        elif action == "alarm-lamp":
            self._toggle_alarm_profile_bool(alarm_id, "lamp_blink")
        elif action == "alarm-delete":
            self._delete_alarm_profile(alarm_id)
            self._premium_close_details()
        elif action == "alarm-snooze":
            self._cycle_alarm_profile_value(alarm_id, "snooze_minutes", [5, 9, 10, 15, 20, 30])
        elif action == "alarm-sound":
            self._cycle_alarm_profile_value(alarm_id, "sound", ["beep", "classic", "soft", "digital"])
        elif action == "alarm-volume":
            self._adjust_alarm_profile_value(alarm_id, "volume", 10, 0, 100)
        elif action == "alarm-lamp-brightness":
            self._adjust_alarm_profile_value(alarm_id, "lamp_brightness", 10, 0, 100)
        elif action == "alarm-pattern":
            self._cycle_alarm_profile_value(alarm_id, "blink_pattern", ["steady", "blink", "pulse"])
        elif action == "alarm-ramp":
            self._cycle_alarm_profile_value(alarm_id, "ramp_up_seconds", [0, 10, 20, 30, 60, 120])
        elif action == "test-audio":
            self._premium_test_audio(alarm_id)

    def _premium_test_audio(self, alarm_id: str) -> None:
        state = getattr(getattr(self._runtime.ctx.core, "state", None), "value", "")
        if state in {"ringing", "snoozed"}:
            self._show_toast("Alarm actief; eerst stoppen via het scherm")
            return
        item = self._alarm_item(alarm_id)
        if item is None:
            return
        from wekker.hardware.mock import MockSpeaker

        speaker = self._runtime.speaker
        if isinstance(speaker, MockSpeaker):
            self._show_toast("Geen audio: de nepspeaker is actief", error=True)
            return
        volume = int(item.get("volume", 70))
        if volume == 0:
            self._show_toast("Volume staat op 0%; verhoog het eerst", error=True)
            return

        self._premium_test_token += 1
        token = self._premium_test_token
        speaker.play(str(item.get("sound", "beep")), volume)

        def stop_test() -> None:
            # Een inmiddels gestart echt alarm mag niet door de test stoppen.
            state_now = getattr(getattr(self._runtime.ctx.core, "state", None), "value", "")
            if token != self._premium_test_token or state_now in {"ringing", "snoozed"}:
                return
            fout = getattr(speaker, "last_error", None)
            speaker.stop()
            if fout:
                self._show_toast(f"Geen geluid: {str(fout)[:90]}", error=True)
            else:
                self._show_toast("Geluidstest klaar")

        self._root.after(1800, stop_test)
        self._show_toast("Geluidstest gestart")

    def _on_user_activity(self, event: Any = None) -> str | None:
        if self._premium_detail_kind == "alarm":
            self._last_activity = time.monotonic()
            if str(getattr(event, "keysym", "") or "").lower() == "p":
                return "break"
        return super()._on_user_activity(event)

    def _maybe_update_sleep_mode(self) -> None:
        if self._premium_detail_kind == "alarm":
            self._last_activity = time.monotonic()
            return
        super()._maybe_update_sleep_mode()

    def _enter_sleep_mode(self) -> None:
        """Rustig thema-slaapscherm zonder iedere seconde een nieuw achtergrondbeeld."""
        if self._sleeping:
            return
        import tkinter as tk

        settings = self._runtime.ctx.settings
        pal = PALETTES.get(self._active_theme, PALETTES["midnight"])
        image = render_sleep_screen(
            self._active_theme, self._premium_now(), self._premium_assets,
            logo_path=self._premium_assets / "wakesync-logo.png",
            view="logo",
            glow=(0 if settings.display.sleep_effect == "off"
                  else settings.display.sleep_glow_intensity),
        )
        photo = ImageTk.PhotoImage(image, master=self._root)
        overlay = tk.Frame(self._root, bg=pal.bg)
        overlay.place(x=0, y=0, width=800, height=480)
        overlay.lift()
        canvas = tk.Canvas(
            overlay, width=800, height=480, bg=pal.bg,
            highlightthickness=0, bd=0,
        )
        canvas.pack(fill="both", expand=True)
        canvas.bind("<Button-1>", self._on_user_activity)
        canvas.create_image(0, 0, image=photo, anchor="nw")
        canvas.create_text(
            400, 265, text="", fill="#FCFEFF",
            font=("DejaVu Sans", 56, "bold"), tags=("sleep_time",),
        )
        canvas.create_text(
            400, 329, text="", fill="#E1EDFF",
            font=("DejaVu Sans", 14), tags=("sleep_date",),
        )
        self._premium_sleep_photo = photo
        self._sleep_overlay = overlay
        self._widgets["_overlay_sleep_canvas"] = canvas
        self._sleeping = True
        self._sleep_phase = 0.0
        self._sleep_render_failures = 0
        self._refresh_sleep_content()
        # Geen agressieve redraw-loop: ook onder Pi-load blijft het alarm reageren.

    def _wake_from_sleep(self) -> None:
        super()._wake_from_sleep()
        self._premium_sleep_photo = None

    def _show_alarm_creator(self) -> None:
        """De originele 360°-tijdkiezer blijft intact; ook de omhulling krijgt stijl."""
        super()._show_alarm_creator()
        pal = PALETTES.get(self._active_theme, PALETTES["midnight"])
        if self._alarm_creator_overlay is not None:
            self._alarm_creator_overlay.configure(bg=pal.bg)
            for child in self._alarm_creator_overlay.winfo_children():
                if child.winfo_class() == "Button":
                    child.configure(
                        bg=pal.raised, fg=pal.text,
                        activebackground=pal.card,
                        activeforeground=pal.text,
                    )

    def _draw_alarm_creator(self) -> None:
        """Behoud alle originele Canvas-tags, aanraakgebieden en draglogica."""
        super()._draw_alarm_creator()
        canvas = self._widgets.get("_alarm_creator_canvas")
        if canvas is None:
            return
        pal = PALETTES.get(self._active_theme, PALETTES["midnight"])
        canvas.configure(bg=pal.bg)

        # Landschap achter de bestaande kalender/dial zonder canvas-tags te wijzigen.
        asset = self._premium_assets / f"premium_{self._active_theme}.png"
        if asset.is_file():
            if (self._premium_creator_photo is None
                    or self._premium_creator_theme != self._active_theme):
                with Image.open(asset) as source:
                    illustration = source.convert("RGB").resize(
                        (800, 480), Image.Resampling.LANCZOS,
                    )
                alpha = 205 if pal.dark else 228
                overlay = Image.new("RGB", (800, 480), pal.bg)
                illustration = Image.blend(illustration, overlay, alpha / 255)
                self._premium_creator_photo = ImageTk.PhotoImage(
                    illustration, master=self._root,
                )
                self._premium_creator_theme = self._active_theme
            canvas.create_image(
                0, 0, image=self._premium_creator_photo, anchor="nw",
                tags=("premium_background",),
            )
            canvas.tag_lower("premium_background")

        mapping = {
            "#050b14": pal.bg,
            "#0b1727": pal.card,
            "#0d1929": pal.card,
            "#13243a": pal.raised,
            "#168cf2": pal.accent,
            "#0b5fa8": pal.accent,
            "#8ea2bd": pal.muted,
            "#f8fafc": pal.text,
            "#405067": pal.muted,
        }
        for item in canvas.find_all():
            for attribute in ("fill", "outline"):
                try:
                    old = str(canvas.itemcget(item, attribute)).lower()
                    if old in mapping:
                        canvas.itemconfigure(item, **{attribute: mapping[old]})
                except Exception:
                    # Niet alle Tk-Canvasobjecten ondersteunen fill/outline.
                    continue

