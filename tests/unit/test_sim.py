"""Tests: simulatiemodus eerste prototype (display/speaker/lamp/button).

Deze tests controleren gedrag van de onderliggende wekker (toestanden,
hardware, agenda), niet de CLI-tekst. De CLI-dispatcher wordt alleen met
één smoke-test geraakt.
"""

import pytest

from wekker.alarm.state import AlarmState
from wekker.hardware.mock import MockSpeaker
from wekker.settings import SettingsError
from wekker.sim import SimOptions, Simulation, _QUIT, demo_transcript, run_command


def _sim(**kwargs) -> Simulation:
    opts = SimOptions(
        start="07:29:50", day="2026-09-17", alarm="07:30",
        snooze_minutes=5, lamp_duration_after_button=30,
    )
    for key, value in kwargs.items():
        setattr(opts, key, value)
    return Simulation(opts)


# -- tijd ---------------------------------------------------------------
def test_advance_activeert_alarm_op_tijd():
    sim = _sim()
    assert sim.core.state is AlarmState.SLEEPING
    sim.advance(9)
    assert sim.core.state is AlarmState.SLEEPING
    sim.advance(1)
    assert sim.core.state is AlarmState.RINGING
    assert sim.stamp() == "07:30:00"


def test_advance_weigert_ongeldige_waarden():
    sim = _sim()
    with pytest.raises(SettingsError):
        sim.advance(-1)
    with pytest.raises(SettingsError):
        sim.advance(86_401)
    with pytest.raises(SettingsError):
        sim.advance("tien")  # type: ignore[arg-type]


def test_snooze_gebruikt_gesimuleerde_tijd():
    sim = _sim()
    sim.advance(10)
    assert sim.snooze() == "snooze: ok (snoozed)"
    assert sim.core.next_alarm().strftime("%H:%M:%S") == "07:35:00"
    sim.advance(299)
    assert sim.core.state is AlarmState.SNOOZED
    sim.advance(1)
    assert sim.core.state is AlarmState.RINGING


def test_ongeldige_opties_geweigerd_bij_opbouw():
    with pytest.raises(SettingsError):
        _sim(alarm="25:00")
    with pytest.raises(SettingsError):
        _sim(start="07:xx")
    with pytest.raises(SettingsError):
        _sim(day="17-09-2026")
    with pytest.raises(SettingsError):
        _sim(lamp_duration_after_button=0)


# -- hardware ------------------------------------------------------------
def test_button_stopt_alarm_en_doet_lamp_uit():
    sim = _sim()
    sim.advance(10)
    assert sim.speaker.is_playing
    assert sim.lamp.is_on
    assert sim.press_button() == "button -> dismissed (lamp: uit)"
    assert sim.core.state is AlarmState.DISMISSED
    assert not sim.speaker.is_playing
    assert not sim.lamp.is_on


def test_button_zet_lamp_tijdelijk_aan_zonder_alarm():
    sim = _sim()
    assert "lamp: aan" in sim.press_button()
    sim.advance(29)
    assert sim.lamp.is_on
    sim.advance(1)
    assert not sim.lamp.is_on


def test_hardwarefout_tijdens_simulatie_logt_en_gaat_door():
    sim = _sim()
    sim.advance(10)
    assert sim.core.state is AlarmState.RINGING

    class Kapot(MockSpeaker):
        def stop(self) -> None:
            raise RuntimeError("speaker stuk")

    sim.core._speaker = Kapot()
    # dismiss faalt op hardware: fout wordt gelogd, simulatie loopt door.
    with pytest.raises(RuntimeError):
        sim.dismiss()
    assert sim.core.state is AlarmState.RINGING
    sim.advance(5)
    assert sim.stamp() == "07:30:05"  # tijd liep wel door
    sim.core._speaker = MockSpeaker()
    assert sim.dismiss() == "dismiss: ok (dismissed)"


# -- scenario's ------------------------------------------------------------
def test_normaal_alarm_button_dismiss():
    sim = _sim()
    sim.advance(10)
    sim.press_button()
    assert sim.core.state is AlarmState.DISMISSED


def test_snooze_daarna_opnieuw_alarm():
    sim = _sim()
    sim.advance(10)
    sim.snooze()
    sim.advance(300)
    assert sim.core.state is AlarmState.RINGING
    assert sim.speaker.is_playing


def test_agenda_correct_weergegeven():
    sim = _sim()
    assert "niet gesynchroniseerd" in sim.status_text()
    assert sim.sync_agenda() == "agenda-sync: ok (4 lessen)"
    sim.press_button()  # wekt ook het display
    assert "Wiskunde" in sim.driver.text
    assert "08:30" in sim.driver.text
    assert "J. Jansen" in sim.display_text()


def test_display_toont_alarm_en_lampmelding():
    sim = _sim()
    sim.sync_agenda()
    sim.advance(10)
    assert "ALARM!" in sim.display_text()
    sim.press_button()
    assert "ALARM!" not in sim.display_text()


def test_eventlog_legt_transities_vast():
    sim = _sim()
    sim.advance(10)
    sim.press_button()
    assert sim.events[0].endswith("sleeping -> ringing")
    assert sim.events[1].endswith("ringing -> dismissed")
    assert "07:30:00" in sim.events[0]


# -- CLI-dispatcher (smoke: gedrag, geen tekstvergelijking) -----------------
def test_run_command_stuurt_gedrag_aan():
    sim = _sim()
    assert run_command(sim, "advance 10") == "+10s -> 07:30:00 ringing"
    assert sim.core.state is AlarmState.RINGING
    assert "dismissed" in run_command(sim, "button")
    assert "onbekend commando" in run_command(sim, "vlieg")
    assert "fout:" in run_command(sim, "advance tien")
    assert "fout:" in run_command(sim, "alarm 25:00")
    assert "lamp-aan" in run_command(sim, "lamp on")
    assert "lamp-uit" in run_command(sim, "lamp off")
    assert run_command(sim, "quit") is _QUIT
    assert "Commando's:" in run_command(sim, "help")


def test_demo_bevat_cyclus_en_lamptimer():
    sim = _sim()
    transcript = demo_transcript(sim)
    volgorde = ["sleeping", "ringing", "dismissed", "lamp: aan"]
    pos = -1
    for toestand in volgorde:
        pos = transcript.index(toestand, pos + 1)
    assert sim.core.state is AlarmState.DISMISSED
    assert not sim.lamp.is_on  # timer afgelopen aan het einde van de demo


def test_main_simulate_demo_draait(capsys):
    from wekker.main import main

    main(["simulate", "--demo"])
    uit = capsys.readouterr().out
    assert "State: dismissed" in uit
    assert "Lamp: uit" in uit


def test_main_simulate_commands_niet_interactief(capsys):
    from wekker.main import main

    with pytest.raises(SystemExit) as exc:
        main(["simulate", "--commands", "advance 10;status"])
    assert exc.value.code == 0
    assert "ringing" in capsys.readouterr().out
