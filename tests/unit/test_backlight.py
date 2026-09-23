from pathlib import Path

from wekker.display.backlight import BacklightController


def test_sysfs_backlight_schaalt_percentage(tmp_path: Path) -> None:
    dev = tmp_path / "rpi_backlight"
    dev.mkdir()
    (dev / "max_brightness").write_text("255", encoding="ascii")
    (dev / "brightness").write_text("0", encoding="ascii")

    ctl = BacklightController(tmp_path)
    assert ctl.set_percent(50) is True
    assert (dev / "brightness").read_text(encoding="ascii") == "128"


def test_backlight_clampt_waarden(tmp_path: Path) -> None:
    dev = tmp_path / "panel"
    dev.mkdir()
    (dev / "max_brightness").write_text("100", encoding="ascii")
    (dev / "brightness").write_text("50", encoding="ascii")

    ctl = BacklightController(tmp_path)
    assert ctl.set_percent(150) is True
    assert (dev / "brightness").read_text(encoding="ascii") == "100"
    assert ctl.set_percent(-20) is True
    assert (dev / "brightness").read_text(encoding="ascii") == "0"
