"""Tests: launch_gui zet echte kiosk-modus (headless, met nep-tkinter).

Alleen ``-fullscreen`` bleek op de Pi onvoldoende (XWayland negeert de hint):
kiosk vereist overrideredirect + exacte geometrie + -fullscreen/-topmost.
"""

import sys
import types

import pytest

from wekker.gui import app as app_module


class FakeRoot:
    def __init__(self):
        self.calls = []

    def attributes(self, *args):
        self.calls.append(("attributes",) + tuple(args))
        return 0

    def overrideredirect(self, waarde):
        self.calls.append(("overrideredirect", waarde))

    def geometry(self, waarde):
        self.calls.append(("geometry", waarde))

    def bind(self, sequentie, _fn):
        self.calls.append(("bind", sequentie))

    def focus_force(self):
        self.calls.append(("focus_force",))

    def mainloop(self):
        self.calls.append(("mainloop",))

    def destroy(self):
        self.calls.append(("destroy",))


class StubApp:
    instanties = []

    def __init__(self, root, runtime):
        self.root = root
        self.runtime = runtime
        StubApp.instanties.append(self)

    def tick(self):
        pass

    def stop(self):
        pass


@pytest.fixture
def nep_tkinter(monkeypatch):
    wortels = []

    def maak_tk():
        wortel = FakeRoot()
        wortels.append(wortel)
        return wortel

    module = types.ModuleType("tkinter")
    module.Tk = maak_tk
    monkeypatch.setitem(sys.modules, "tkinter", module)
    monkeypatch.setattr(app_module, "TouchApp", StubApp)
    StubApp.instanties.clear()
    return wortels


def test_kiosk_gebruikt_overrideredirect_en_volledig_scherm(nep_tkinter):
    app_module.launch_gui(object(), fullscreen=True)
    (wortel,) = nep_tkinter
    assert ("overrideredirect", True) in wortel.calls
    assert ("geometry", "800x480+0+0") in wortel.calls
    assert ("attributes", "-fullscreen", True) in wortel.calls
    assert ("attributes", "-topmost", True) in wortel.calls
    assert ("focus_force",) in wortel.calls
    assert ("bind", "<Escape>") in wortel.calls
    assert ("mainloop",) in wortel.calls
    (instantie,) = StubApp.instanties
    assert instantie.root is wortel


def test_window_modus_blijft_normaal_venster(nep_tkinter):
    app_module.launch_gui(object(), fullscreen=False)
    (wortel,) = nep_tkinter
    assert not [c for c in wortel.calls if c[0] == "overrideredirect"]
    assert ("attributes", "-fullscreen", False) in wortel.calls
    assert ("geometry", "800x480") in wortel.calls
    assert not [c for c in wortel.calls if c == ("attributes", "-topmost", True)]
