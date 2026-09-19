"""Regressietests: GUI ververst zonder flicker (geen destroy/recreate per tick).

De TouchApp.tick() loopt iedere seconde via render(). Vroeger werd daarbij
de hele widgetboom gedestroyed en opnieuw opgebouwd (zichtbare flash).
Nu worden widgets hergebruikt en alleen veranderde teksten aangepast.
Deze tests draaien headless met een nep-tkinter.
"""

from wekker.gui import app as app_module
from wekker.gui.app import TouchApp
from wekker.gui.screens import (
    AgendaScreenData,
    GuiData,
    MainScreenData,
    Navigator,
)


class FakeWidget:
    def __init__(self, parent=None, **kwargs):
        self.parent = parent
        self.text = kwargs.get("text", "")
        self.config_calls = 0
        self.destroyed = False
        self.children = []
        if parent is not None and hasattr(parent, "children"):
            parent.children.append(self)

    # tkinter API die TouchApp gebruikt
    def cget(self, key):
        assert key == "text"
        return self.text

    def config(self, **kwargs):
        self.config_calls += 1
        if "text" in kwargs:
            self.text = kwargs["text"]

    def pack(self, *args, **kwargs):
        return None

    def pack_forget(self, *args, **kwargs):
        return None

    def destroy(self):
        self.destroyed = True
        if self.parent is not None and hasattr(self.parent, "children"):
            try:
                self.parent.children.remove(self)
            except ValueError:
                pass


class FakeFrame(FakeWidget):
    def winfo_children(self):
        return list(self.children)


class FakeTk:
    Frame = FakeWidget
    Label = FakeWidget
    Button = FakeWidget


class FakeRoot:
    def title(self, *args, **kwargs):
        return None

    def geometry(self, *args, **kwargs):
        return None


class HeadlessApp(TouchApp):
    """TouchApp zonder echte tkinter."""

    def _tk(self):
        return FakeTk

    def _make_frame(self):
        return FakeFrame(parent=None)


def _data_main(time_str="07:32", alarm_str="07:30"):
    return GuiData(
        main=MainScreenData(time_str=time_str, alarm_str=alarm_str),
        agenda=AgendaScreenData(provider_name="OSIRIS", day_label="Vandaag"),
    )


def _make_app(monkeypatch, data):
    monkeypatch.setattr(app_module, "build_gui_data", lambda _rt: data)
    return HeadlessApp(FakeRoot(), runtime=object(), navigator=Navigator())


def test_tweede_render_met_zelfde_data_destroyed_niets(monkeypatch):
    data = _data_main()
    app = _make_app(monkeypatch, data)
    widgets_eerste_keer = dict(app._widgets)
    assert widgets_eerste_keer, "eerste render moet widgets aanmaken"

    app.render()  # tweede tick, zelfde data

    assert app._widgets == widgets_eerste_keer, "widgets moeten hergebruikt worden"
    for widget in app._widgets.values():
        assert not widget.destroyed
    assert app._frame.winfo_children(), "frame mag niet leeg achterblijven"


def test_alarmwijziging_past_alleen_tekst_aan(monkeypatch):
    data = _data_main(time_str="07:32")
    app = _make_app(monkeypatch, data)
    time_label = app._widgets["time"]
    alarm_label = app._widgets["alarm"]
    time_config_calls = time_label.config_calls

    data.main = MainScreenData(time_str="07:33", alarm_str="07:30")
    app.render()

    assert app._widgets["time"] is time_label, "tijd-widget moet hetzelfde object blijven"
    assert app._widgets["alarm"] is alarm_label, "alarm-widget moet hetzelfde object blijven"
    assert time_label.text == "07:33"
    assert time_label.config_calls == time_config_calls + 1
    assert alarm_label.config_calls == 0, "onveranderde tekst mag geen config() krijgen"
    assert not time_label.destroyed


def test_agenda_rijwijziging_hergebruikt_widgets(monkeypatch):
    from wekker.gui.screens import AgendaRow

    data = GuiData(
        main=MainScreenData(time_str="07:32", alarm_str="07:30"),
        agenda=AgendaScreenData(
            provider_name="OSIRIS",
            day_label="Vandaag",
            rows=(AgendaRow(time_str="09:00", subject="Wiskunde"),),
            simulated=True,
        ),
    )
    app = _make_app(monkeypatch, data)
    app._nav.go_left()  # naar agenda-scherm
    app.render()
    rij_label = app._widgets["rows"][0]
    titel = app._widgets["title"]

    data.agenda = AgendaScreenData(
        provider_name="OSIRIS",
        day_label="Vandaag",
        rows=(AgendaRow(time_str="09:00", subject="Nederlands"),),
        simulated=True,
    )
    layout = app.render()

    assert layout["screen"] == "agenda"
    assert app._widgets["rows"][0] is rij_label, "rij-widget moet hergebruikt worden"
    assert app._widgets["title"] is titel
    assert rij_label.text == "09:00  Nederlands"
    assert not rij_label.destroyed


def test_schermwissel_bouwt_opnieuw_op(monkeypatch):
    data = _data_main()
    app = _make_app(monkeypatch, data)
    oude_widgets = dict(app._widgets)

    app._nav.go_left()  # naar agenda-scherm
    layout = app.render()

    assert layout["screen"] == "agenda"
    assert app._widgets is not oude_widgets
    assert all(w.destroyed for w in oude_widgets.values())
    assert app._widgets["title"].text == "OSIRIS"
