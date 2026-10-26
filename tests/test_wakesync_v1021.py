"""Regressietests 10.2.1: rendering, klikroutes, launcher en veilige installatie.

De legacy-schermfuncties worden voor kliktests vervangen door registratiecallbacks.
Dit is geen bewijs van fysieke Raspberry Pi-, labwc- of speakerwerking.
"""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import sys
import types
from datetime import datetime
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from wekker.gui.premium_render import render_screen, render_detail_screen, PALETTES
from wekker import desktop
import install_wakesync_desktop as desk
import apply_wakesync_v1021 as updater
from wakesync_install_common import apply_transaction, restore_transaction

NOW = datetime(2026, 10, 26, 7, 30)
ASSETS = ROOT / "src/wekker/assets"


def settings():
    return types.SimpleNamespace(
        locale=types.SimpleNamespace(timezone="Europe/Amsterdam", time_format="24h"),
        display=types.SimpleNamespace(sleep_after_seconds=60, sleep_view="logo_time_date",
            sleep_effect="soft_glow", sleep_glow_intensity=65, brightness=80),
    )


def layouts():
    alarm = dict(id="a", time="07:45", enabled=True, day_label="Morgen",
                 snooze_minutes=9, speaker_enabled=True, lamp_blink=True)
    return [
        dict(screen="main", time="07:30", alarm="07:45", alarm_day="Morgen",
             lesson_subject="Netwerkbeheer", lesson_time="08:30 - 10:00",
             lesson_room="E2.12", agenda_status="Bijgewerkt"),
        dict(screen="agenda", day="Maandag 26 oktober", rows=[
            dict(start=f"{8+i:02d}:15", subject="Een voorbeeldvak", room="E2.12", current=i==0)
            for i in range(6)], page=1, page_count=3, total_rows=15),
        dict(screen="alarm", items=[dict(alarm, id=str(i)) for i in range(8)]),
        dict(screen="settings", timezone="Europe/Amsterdam", time_format="24h",
             sleep_after_seconds=60, sleep_glow_intensity=65),
    ]


def assert_separate(hits):
    for i, a in enumerate(hits):
        assert 0 <= a.x0 < a.x1 <= 800 and 0 <= a.y0 < a.y1 <= 480
        for b in hits[i+1:]:
            assert not (
                max(a.x0, b.x0) < min(a.x1, b.x1)
                and max(a.y0, b.y0) < min(a.y1, b.y1)
            ), f"Overlappende raakvlakken: {a} / {b}"


@pytest.mark.parametrize("theme", list(PALETTES))
@pytest.mark.parametrize("page", range(4))
def test_four_pages_all_themes_without_overlapping_hit_targets(theme, page):
    image, hits = render_screen(layouts()[page], theme, NOW, ASSETS, alarm_list_page=1)
    assert image.size == (800,480)
    assert image.mode == "RGB"
    assert_separate(hits)


@pytest.mark.parametrize("theme", list(PALETTES))
@pytest.mark.parametrize("kind", ["display", "alarm"])
def test_detail_pages_all_themes_without_overlapping_hit_targets(theme, kind):
    alarm = layouts()[2]["items"][0]
    image, hits = render_detail_screen(kind, theme, NOW, ASSETS, settings=settings(), item=alarm)
    assert image.size == (800,480)
    assert_separate(hits)


def test_navigation_larger_and_lower():
    _, hits = render_screen(layouts()[0],"midnight",NOW,ASSETS)
    navigation = [h for h in hits if h.action=="nav" and h.y0<80]
    assert len(navigation)==4
    assert all(h.y1-h.y0==58 for h in navigation)
    assert all(h.y0==19 and h.y1==77 for h in navigation)
    assert 58 / 46 >= 1.25  # Raakhoogte minstens +25%.


def test_settings_software_and_diagnostics_have_correct_action_and_payload():
    _,hits=render_screen(layouts()[3],"midnight",NOW,ASSETS)
    assert {(h.action,h.payload) for h in hits if h.action=="settings"} == {
        ("settings","software"),("settings","diagnostics"),
    }


@pytest.mark.parametrize("theme",list(PALETTES))
@pytest.mark.parametrize("section",["software","diagnostics"])
def test_rendered_tile_reaches_real_dispatch_path(monkeypatch,theme,section):
    from wekker.gui.premium import PremiumTouchApp
    _, hits = render_screen(layouts()[3],theme,NOW,ASSETS)
    app = PremiumTouchApp.__new__(PremiumTouchApp)
    app._premium_hits=hits
    calls=[]
    app._premium_close_details=lambda:None
    app._show_toast=lambda *a,**k:calls.append(("ERROR",a,k))
    from wekker.gui.settings_routes_v1021 import ROUTES
    route=ROUTES[section]
    setattr(app,route["method"],lambda *args:calls.append((section,list(args))))
    hit=next(h for h in hits if h.action=="settings" and h.payload==section)
    event=types.SimpleNamespace(x=(hit.x0+hit.x1)//2,y=(hit.y0+hit.y1)//2)
    assert app._premium_click(event)=="break"
    assert calls==[(section,route["args"])]


def test_route_selection_supports_existing_named_methods():
    source='class TouchApp:\n    def _show_update_overlay(self): pass\n    def _show_diagnostics(self): pass\n'
    assert updater.choose_routes(source)=={
        "software":{"method":"_show_update_overlay","args":[]},
        "diagnostics":{"method":"_show_diagnostics","args":[]},
    }


def test_route_selection_generic_existing_section():
    source='class TouchApp:\n    def _show_settings_section(self, section):\n        if section == "software": pass\n        elif section == "diagnostics": pass\n'
    routes=updater.choose_routes(source)
    assert routes["software"]["args"]==["software"]
    assert routes["diagnostics"]["args"]==["diagnostics"]


def test_route_selection_refuses_guessed_missing_handlers():
    with pytest.raises(ValueError,match="Geen aantoonbaar"):
        updater.choose_routes("class TouchApp:\n    def _show_settings_section(self, x): pass\n")


def make_repo(path):
    path.mkdir(parents=True,exist_ok=True)
    (path/".venv/bin").mkdir(parents=True)
    (path/".venv/bin/python").write_text("fixture")
    (path/"tools").mkdir()
    (path/"tools/wakesync_launch.py").write_text("# fixture")
    (path/"src/wekker/gui").mkdir(parents=True)
    (path/"src/wekker/desktop.py").write_text("# fixture")
    (path/"src/wekker/gui/app.py").write_text("# fixture")
    (path/"wekker-settings.json").write_text('{"private":"keep"}')
    return path


def test_launcher_always_absolute_settings_and_own_interpreter(tmp_path):
    repo=make_repo(tmp_path/"project met spaties")
    command=desktop.build_command(repo)
    assert command==[
        str(repo/".venv/bin/python"),"-m","wekker","gui","--settings",
        str(repo/"wekker-settings.json"),
    ]
    assert desktop.build_command(repo,window=True)[-1]=="--window"


def test_launcher_missing_settings_refuses_empty_defaults(tmp_path):
    repo=make_repo(tmp_path/"repo")
    (repo/"wekker-settings.json").unlink()
    with pytest.raises(desktop.LaunchError,match="Instellingen ontbreken"):
        desktop.build_command(repo)


def test_single_instance_lock_released(tmp_path):
    with desktop.single_instance(tmp_path) as first:
        assert first
        with desktop.single_instance(tmp_path) as second:
            assert not second
    with desktop.single_instance(tmp_path) as third:
        assert third


def test_focus_request_changes_timestamp(tmp_path):
    desktop.request_focus(tmp_path)
    first=(tmp_path/"focus-request").read_bytes()
    desktop.request_focus(tmp_path)
    second=(tmp_path/"focus-request").read_bytes()
    assert first!=second


def process(proc, pid, display=":0", authority="/home/test/.Xauthority"):
    directory=proc/str(pid)
    directory.mkdir(parents=True)
    (directory/"comm").write_text("pcmanfm\n")
    (directory/"cmdline").write_bytes(b"pcmanfm\0--desktop\0")
    (directory/"environ").write_bytes(
        f"DISPLAY={display}\0WAYLAND_DISPLAY=wayland-0\0XAUTHORITY={authority}\0".encode()
    )


def test_ssh_uses_local_session_no_xhost(tmp_path):
    process(tmp_path,1234)
    env=desktop.local_display_environment({"SSH_CONNECTION":"ssh","DISPLAY":"localhost:10.0"},tmp_path)
    assert env["DISPLAY"]==":0"
    assert env["XAUTHORITY"]=="/home/test/.Xauthority"


def test_multiple_graphical_sessions_refused(tmp_path):
    process(tmp_path,1234,":0")
    process(tmp_path,1235,":1")
    with pytest.raises(desktop.LaunchError,match="Meerdere"):
        desktop.local_display_environment({"SSH_CONNECTION":"ssh"},tmp_path)


def test_no_graphical_session_has_clear_error(tmp_path):
    with pytest.raises(desktop.LaunchError,match="Geen lokaal"):
        desktop.local_display_environment({"SSH_CONNECTION":"ssh"},tmp_path)


def test_existing_local_environment_preserved(tmp_path):
    values={"DISPLAY":":0","XAUTHORITY":"/tmp/auth"}
    assert desktop.local_display_environment(values,tmp_path)==values


def test_desktop_exec_safe_quoting():
    assert desk.exec_arg("/home/test/project map")=='"/home/test/project map"'
    with pytest.raises(ValueError):
        desk.exec_arg("bad\ncommand")
    text=desk.desktop_contents(Path("/home/test/project map"),Path("/home/test/.local/bin/wakesync"))
    assert 'Exec="/home/test/.local/bin/wakesync"' in text
    assert "Terminal=false" in text
    assert "Projectmap openen" in text


def test_installation_preserves_calibration_and_settings_and_can_restore(tmp_path):
    repo=make_repo(tmp_path/"repo")
    home=tmp_path/"home"
    (home/".config/labwc").mkdir(parents=True)
    calibration=home/".config/labwc/rc.xml"
    calibration.write_bytes(b"<labwc_config>KEEP-CALIBRATION</labwc_config>\n")
    before_cal=calibration.read_bytes()
    before_settings=(repo/"wekker-settings.json").read_bytes()
    plan=desk.make_plan(repo,home,home/"Desktop",autostart=True,merge_active=True)
    assert calibration not in plan
    backup=apply_transaction(plan,tmp_path/"backups")
    assert calibration.read_bytes()==before_cal
    assert (repo/"wekker-settings.json").read_bytes()==before_settings
    auto=(home/".config/labwc/autostart").read_text()
    assert "--autostart &" in auto
    assert not desk.make_plan(repo,home,home/"Desktop",autostart=True,merge_active=True)
    restore_transaction(backup)
    assert not (home/"Desktop/WakeSync.desktop").exists()
    assert calibration.read_bytes()==before_cal


def test_nonmerge_preserves_system_autostart_after_disabling(tmp_path):
    repo=make_repo(tmp_path/"repo")
    home=tmp_path/"home"
    home.mkdir()
    system=tmp_path/"system-autostart"
    system.write_text("panel &\n")
    plan=desk.make_plan(repo,home,home/"Desktop",autostart=True,
                        merge_active=False,system_autostart=system)
    target=home/".config/labwc/autostart"
    content=plan[target][1].decode()
    disabled=desk.managed_block(content,None)
    assert str(system) in disabled
    assert "--autostart &" not in disabled


def test_existing_autostart_is_appended_not_replaced(tmp_path):
    repo=make_repo(tmp_path/"repo")
    home=tmp_path/"home"
    auto=home/".config/labwc/autostart"
    auto.parent.mkdir(parents=True)
    auto.write_text("# My panel\npanel &\n")
    plan=desk.make_plan(repo,home,home/"Desktop",autostart=True,merge_active=True)
    assert plan[auto][1].decode().startswith("# My panel\npanel &\n")


def test_exit_in_autostart_refuses_unreachable_start(tmp_path):
    repo=make_repo(tmp_path/"repo")
    home=tmp_path/"home"
    auto=home/".config/labwc/autostart"
    auto.parent.mkdir(parents=True)
    auto.write_text("exit 0\n")
    with pytest.raises(ValueError,match="exit/exec"):
        desk.make_plan(repo,home,home/"Desktop",autostart=True)
    assert auto.read_text()=="exit 0\n"


def test_partial_managed_block_refuses():
    with pytest.raises(ValueError):
        desk.managed_block(desk.START,"echo test")


def test_transaction_restores_exact_bytes_and_mode(tmp_path):
    a=tmp_path/"a"
    a.write_bytes(b"old\r\n")
    a.chmod(0o640)
    b=tmp_path/"b"
    manifest=apply_transaction({a:(a.read_bytes(),b"new\n",0o600),b:(None,b"new",0o644)},tmp_path/"backups")
    restore_transaction(manifest)
    assert a.read_bytes()==b"old\r\n"
    assert a.stat().st_mode&0o777==0o640
    assert not b.exists()


def test_restore_refuses_later_edits(tmp_path):
    path=tmp_path/"a"
    manifest=apply_transaction({path:(None,b"new",0o644)},tmp_path/"backups")
    path.write_bytes(b"user changed")
    with pytest.raises(ValueError,match="Later gewijzigd"):
        restore_transaction(manifest)
    assert path.read_bytes()==b"user changed"


def test_transaction_rejects_changed_file_before_any_write(tmp_path):
    a=tmp_path/"a"; b=tmp_path/"b"
    a.write_bytes(b"old"); b.write_bytes(b"changed")
    with pytest.raises(ValueError):
        apply_transaction({a:(b"old",b"new",0o644),b:(b"old",b"new",0o644)},tmp_path/"backups")
    assert a.read_bytes()==b"old"


def test_transaction_rejects_symlink(tmp_path):
    actual=tmp_path/"actual"; actual.write_text("keep")
    link=tmp_path/"link"; link.symlink_to(actual)
    with pytest.raises(ValueError,match="Symbolische"):
        apply_transaction({link:(b"keep",b"new",0o644)},tmp_path/"backups")
    assert actual.read_text()=="keep"


def test_project_metadata_preserves_original_entrypoint_and_is_idempotent():
    content='[project]\nname="wekker"\nversion="10.2.0"\n[project.scripts]\nwekker="wekker.main:main"\n'
    updated=updater.updated_project(content)
    assert 'wekker="wekker.main:main"' in updated
    assert 'wakesync = "wekker.desktop:main"' in updated
    assert updater.updated_project(updated)==updated


def test_project_other_version_refused():
    with pytest.raises(ValueError):
        updater.updated_project('[project]\nversion="11.0.0"\n')


def test_source_payload_integrity_and_idempotence():
    # Test draait na toepassen van het updatepakket op de echte of test-repository.
    assert updater.build_plan(ROOT)=={}


def test_existing_routes_correspond_to_available_real_class_methods():
    desktop.validate_gui_routes()
