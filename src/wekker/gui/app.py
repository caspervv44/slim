"""Fullscreen touchscreen-app (800x480) op basis van tkinter.

Keuzes:
- tkinter uit de stdlib: geen extra dependencies, werkt op Raspberry Pi OS
  en op de laptop (voor development met ``--window``).
- Kiosk-modus op de Pi: ``overrideredirect(True)`` (géén titlebar/WM-randen),
  exacte geometrie ``800x480+0+0`` plus ``-fullscreen`` en ``-topmost``, zodat
  ook het desktop-panel verdwijnt. Alleen ``-fullscreen`` bleek onvoldoende:
  dat is slechts een verzoek aan de windowmanager, dat onder XWayland
  (Raspberry Pi OS) niet volledig wordt gehonoreerd. Touchscreen-aanrakingen
  blijven werken (pointer-events, geen windowmanager nodig); Alt+Tab vervalt
  in kiosk-modus.
- Escape sluit af (development/testen), F11 schakelt fullscreen.
- De app rendert layout-dicts uit ``wekker.gui.screens`` en leest alle data
  uit de bestaande Runtime (core/settings/agenda). Geen eigen alarm- of
  agendalogica.

Opstarten op de Pi: ``python -m wekker gui`` (fullscreen).
Development: ``python -m wekker gui --window`` (venster 800x480).
"""

from __future__ import annotations

import logging
from typing import Any

from wekker.gui.screens import (
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    GuiData,
    Navigator,
    ScreenId,
    build_agenda_data,
    build_main_data,
    layout_for,
)

log = logging.getLogger(__name__)

#: Verversinterval van klok/scherm (ms).
REFRESH_MS = 1000


def build_gui_data(runtime: Any) -> GuiData:
    """Momentopname uit de bestaande Runtime. Enige koppeling tussen GUI en
    wekkerlogica; alles hier komt uit core/settings/agenda."""
    from wekker.agenda.providers import get_provider_info

    ctx = runtime.ctx
    now = ctx.clock.now()
    try:
        provider_name = get_provider_info(ctx.settings.agenda.provider).display_name
    except ValueError:
        provider_name = ctx.settings.agenda.provider
    return GuiData(
        main=build_main_data(now, ctx.core.next_alarm(now)),
        agenda=build_agenda_data(
            ctx.cache.get_day(now.date()), provider_name=provider_name,
        ),
    )


class TouchApp:
    """Rendert scherm-layouts naar tkinter. Aangestuurd door Navigator."""

    def __init__(self, root: Any, runtime: Any, navigator: Navigator | None = None) -> None:
        self._root = root
        self._runtime = runtime
        self._nav = navigator or Navigator()
        self._running = True
        root.title("Aventus Wekker")
        try:
            root.geometry(f"{SCREEN_WIDTH}x{SCREEN_HEIGHT}")
        except Exception:  # pragma: no cover - afhankelijk van backend
            pass
        self._frame = self._make_frame()
        # Widgets worden één keer opgebouwd en daarna alleen bijgewerkt.
        # Volledig destroyen/rebuilden iedere seconde gaf een zichtbare
        # flash; daarom houdt render() bestaande widgets in leven en past
        # het alleen veranderde teksten aan via config().
        self._screen: str | None = None
        self._widgets: dict[str, Any] = {}
        self.render()

    # -- tkinter-fabriekjes (overschrijfbaar/testbaar, dunne schil) --------
    def _make_frame(self) -> Any:
        tk = self._tk()
        frame = tk.Frame(self._root, bg="black")
        frame.pack(fill="both", expand=True)
        return frame

    def _tk(self) -> Any:
        import tkinter as tk

        return tk

    def _clear(self) -> None:
        for child in self._frame.winfo_children():
            child.destroy()

    # -- render ------------------------------------------------------------
    def render(self) -> dict:
        """Werk het actieve scherm bij. Geeft de layout terug (tests).

        Widgets worden hergebruikt: alleen bij een schermwissel of een
        structurele wijziging (rijen/badge aan/uit) wordt opnieuw
        opgebouwd, verder worden alleen veranderde teksten aangepast.
        """
        layout = layout_for(self._nav, build_gui_data(self._runtime))
        if layout["screen"] != self._screen:
            self._rebuild(layout)
        elif layout["screen"] == ScreenId.MAIN.value:
            self._update_main(layout)
        else:
            self._update_agenda(layout)
        return layout

    def _rebuild(self, layout: dict) -> None:
        """Bouw het scherm volledig opnieuw (schermwissel of structuurwijziging)."""
        self._clear()
        self._widgets = {}
        self._screen = layout["screen"]
        if layout["screen"] == ScreenId.MAIN.value:
            self._build_main(layout)
        else:
            self._build_agenda(layout)

    @staticmethod
    def _set_text(widget: Any, text: str) -> None:
        """Pas de tekst aan, maar alleen als hij echt veranderd is."""
        try:
            current = widget.cget("text")
        except Exception:
            current = None
        if current != text:
            widget.config(text=text)

    def _build_main(self, layout: dict) -> None:
        tk = self._tk()
        time_label = tk.Label(self._frame, text=layout["time"], font=("DejaVu Sans", 130),
                              fg="white", bg="black")
        time_label.pack(pady=(30, 0))
        alarm_label = tk.Label(self._frame, text=f'{layout["alarm_label"]}  {layout["alarm"]}',
                               font=("DejaVu Sans", 44), fg="#cccccc", bg="black")
        alarm_label.pack(pady=(10, 20))
        self._widgets["time"] = time_label
        self._widgets["alarm"] = alarm_label
        self._render_arrows(layout)

    def _update_main(self, layout: dict) -> None:
        self._set_text(self._widgets["time"], layout["time"])
        self._set_text(self._widgets["alarm"], f'{layout["alarm_label"]}  {layout["alarm"]}')

    def _build_agenda(self, layout: dict) -> None:
        tk = self._tk()
        title = tk.Label(self._frame, text=layout["title"], font=("DejaVu Sans", 36),
                         fg="white", bg="black")
        title.pack(pady=(16, 0))
        day = tk.Label(self._frame, text=layout["day"], font=("DejaVu Sans", 24),
                       fg="#cccccc", bg="black")
        day.pack()
        self._widgets["title"] = title
        self._widgets["day"] = day
        if layout["simulated"]:
            badge = tk.Label(self._frame, text="demo-data", font=("DejaVu Sans", 20),
                             fg="black", bg="#ffd75e")
            badge.pack(pady=(4, 4))
            self._widgets["badge"] = badge
        if layout["empty_text"]:
            empty = tk.Label(self._frame, text=layout["empty_text"],
                             font=("DejaVu Sans", 28), fg="#cccccc", bg="black")
            empty.pack(pady=20)
            self._widgets["empty"] = empty
        rows = []
        for row in layout["rows"]:
            label = tk.Label(self._frame, text=f'{row["time"]}  {row["subject"]}',
                             font=("DejaVu Sans", 32), fg="white", bg="black",
                             anchor="w")
            label.pack(fill="x", padx=90)
            rows.append(label)
        self._widgets["rows"] = rows
        self._render_arrows(layout)

    def _update_agenda(self, layout: dict) -> None:
        # Structurele wijzigingen (badge aan/uit, lege-melding aan/uit of
        # ander aantal rijen) zijn zeldzaam: bouw dan opnieuw op. De hete
        # lus (zelfde scherm, zelfde structuur) raakt nooit destroy() aan.
        rows = self._widgets.get("rows", [])
        if (bool(self._widgets.get("badge")) != bool(layout["simulated"])
                or bool(self._widgets.get("empty")) != bool(layout["empty_text"])
                or len(rows) != len(layout["rows"])):
            self._rebuild(layout)
            return
        self._set_text(self._widgets["title"], layout["title"])
        self._set_text(self._widgets["day"], layout["day"])
        if layout["empty_text"]:
            self._set_text(self._widgets["empty"], layout["empty_text"])
        for label, row in zip(rows, layout["rows"]):
            self._set_text(label, f'{row["time"]}  {row["subject"]}')
        # Pijlen zijn statisch per scherm; targets veranderen niet zonder
        # schermwissel, dus geen update nodig.

    def _render_arrows(self, layout: dict) -> None:
        tk = self._tk()
        bar = tk.Frame(self._frame, bg="black")
        bar.pack(side="bottom", fill="x", pady=20)
        left = tk.Button(bar, text=layout["left"]["label"], font=("DejaVu Sans", 56),
                         fg="white", bg="#222222", activebackground="#444444",
                         width=3, height=1,
                         command=lambda: self._go(layout["left"]["target"]))
        left.pack(side="left", padx=30)
        right = tk.Button(bar, text=layout["right"]["label"], font=("DejaVu Sans", 56),
                          fg="white", bg="#222222", activebackground="#444444",
                          width=3, height=1,
                          command=lambda: self._go(layout["right"]["target"]))
        right.pack(side="right", padx=30)

    def _go(self, target: str) -> None:
        self._nav.go(ScreenId(target))
        self.render()

    # -- loop ---------------------------------------------------------------
    def tick(self) -> None:
        """Eén slag: wekkerlogica + scherm verversen. Stopt zichzelf netjes."""
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
    """Start de touchscreen-GUI. Importeert tkinter pas hier, zodat de rest
    van de app (en tests) ook zonder display werkt."""
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
        # Echte kiosk: geen WM-decoraties (titlebar) en exact 800x480
        # linksboven, boven het desktop-panel. -fullscreen alleen is slechts
        # een hint die XWayland op de Pi negeert; overrideredirect dwingt af.
        # Touch blijft werken; Escape blijft de uitweg (Alt+Tab vervalt).
        root.overrideredirect(True)
        root.geometry(f"{SCREEN_WIDTH}x{SCREEN_HEIGHT}+0+0")
        root.attributes("-fullscreen", True)
        root.attributes("-topmost", True)
        try:
            root.focus_force()
        except Exception:  # pragma: no cover - afhankelijk van backend
            pass
    else:
        root.attributes("-fullscreen", False)
        root.geometry(f"{SCREEN_WIDTH}x{SCREEN_HEIGHT}")
    # Escape = afsluiten (development/testen).
    root.bind("<Escape>", lambda _e: app.stop())
    root.bind("<F11>", lambda _e: root.attributes(
        "-fullscreen", not bool(root.attributes("-fullscreen"))))
    app = TouchApp(root, runtime)
    app.tick()
    try:
        root.mainloop()
    finally:
        app.stop()
