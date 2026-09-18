"""Fullscreen touchscreen-app (800x480) op basis van tkinter.

Keuzes:
- tkinter uit de stdlib: geen extra dependencies, werkt op Raspberry Pi OS
  en op de laptop (voor development met ``--window``).
- Géén ``override-redirect``: het venster gebruikt ``-fullscreen`` zodat de
  windowmanager actief blijft en Alt+Tab gewoon werkt. De GUI vervangt de
  desktop niet.
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
        """Render het actieve scherm opnieuw. Geeft de layout terug (tests)."""
        layout = layout_for(self._nav, build_gui_data(self._runtime))
        self._clear()
        if layout["screen"] == ScreenId.MAIN.value:
            self._render_main(layout)
        else:
            self._render_agenda(layout)
        return layout

    def _render_main(self, layout: dict) -> None:
        tk = self._tk()
        tk.Label(self._frame, text=layout["time"], font=("DejaVu Sans", 130),
                 fg="white", bg="black").pack(pady=(30, 0))
        tk.Label(self._frame, text=f'{layout["alarm_label"]}  {layout["alarm"]}',
                 font=("DejaVu Sans", 44), fg="#cccccc", bg="black").pack(pady=(10, 20))
        self._render_arrows(layout)

    def _render_agenda(self, layout: dict) -> None:
        tk = self._tk()
        tk.Label(self._frame, text=layout["title"], font=("DejaVu Sans", 36),
                 fg="white", bg="black").pack(pady=(16, 0))
        tk.Label(self._frame, text=layout["day"], font=("DejaVu Sans", 24),
                 fg="#cccccc", bg="black").pack()
        if layout["simulated"]:
            tk.Label(self._frame, text="demo-data", font=("DejaVu Sans", 20),
                     fg="black", bg="#ffd75e").pack(pady=(4, 4))
        if layout["empty_text"]:
            tk.Label(self._frame, text=layout["empty_text"],
                     font=("DejaVu Sans", 28), fg="#cccccc", bg="black").pack(pady=20)
        for row in layout["rows"]:
            tk.Label(self._frame, text=f'{row["time"]}  {row["subject"]}',
                     font=("DejaVu Sans", 32), fg="white", bg="black",
                     anchor="w").pack(fill="x", padx=90)
        self._render_arrows(layout)

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
    root.attributes("-fullscreen", bool(fullscreen))
    if not fullscreen:
        root.geometry(f"{SCREEN_WIDTH}x{SCREEN_HEIGHT}")
    # Escape = afsluiten (development/testen). Alt+Tab blijft werken omdat
    # het venster een normaal fullscreen-venster is (geen override-redirect).
    root.bind("<Escape>", lambda _e: app.stop())
    root.bind("<F11>", lambda _e: root.attributes(
        "-fullscreen", not bool(root.attributes("-fullscreen"))))
    app = TouchApp(root, runtime)
    app.tick()
    try:
        root.mainloop()
    finally:
        app.stop()
