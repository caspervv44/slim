from __future__ import annotations

import io
import json
from pathlib import Path
import zipfile

import pytest

from wekker.updater import SoftwareUpdater, UpdateError, UpdateInfo, _version_tuple


def _archive(version: str = "8.0.0") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "slim-main/pyproject.toml",
            f'[project]\nname = "wekker"\nversion = "{version}"\n',
        )
        zf.writestr("slim-main/src/wekker/__init__.py", '__version__ = "8.0.0"\n')
        zf.writestr("slim-main/README.md", "# WakeSync\n")
    return buf.getvalue()


def test_version_parser_semver() -> None:
    assert _version_tuple("v7.2.1") == (7, 2, 1)
    assert _version_tuple("8") == (8, 0, 0)
    with pytest.raises(UpdateError):
        _version_tuple("geen-versie")


def test_release_wordt_gekozen_als_hij_nieuwer_is(tmp_path: Path, monkeypatch) -> None:
    updater = SoftwareUpdater(
        "caspervv44/slim", current_version="7.0.0", project_root=tmp_path
    )

    def fake(url: str, _limit: int) -> bytes:
        assert "/releases/latest" in url
        return json.dumps({
            "tag_name": "v8.0.0",
            "zipball_url": "https://example.test/v8.zip",
            "body": "Nieuwe versie",
        }).encode()

    monkeypatch.setattr(updater, "_request_bytes", fake)
    info = updater.check()
    assert info.available is True
    assert info.latest_version == "8.0.0"
    assert info.source == "GitHub Release"


def test_main_branch_is_fallback_zonder_release(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WAKESYNC_UPDATE_ALLOW_BRANCH", "1")
    updater = SoftwareUpdater(
        "caspervv44/slim", current_version="7.0.0", project_root=tmp_path
    )

    def fake(url: str, _limit: int) -> bytes:
        if "/releases/latest" in url:
            raise UpdateError("updateserver gaf HTTP 404")
        assert "/main/pyproject.toml" in url
        return b'[project]\nname="wekker"\nversion="8.0.0"\n'

    monkeypatch.setattr(updater, "_request_bytes", fake)
    info = updater.check()
    assert info.available is True
    assert info.latest_version == "8.0.0"
    assert info.source == "GitHub main (ontwikkelkanaal)"
    assert info.download_url.endswith("/archive/refs/heads/main.zip")


def test_prepare_controleert_project_en_schrijft_worker(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="wekker"\nversion="7.0.0"\n', encoding="utf-8"
    )
    updater = SoftwareUpdater(
        "caspervv44/slim", current_version="7.0.0", project_root=tmp_path
    )
    monkeypatch.setattr(updater, "_request_bytes", lambda _url, _limit: _archive())
    info = UpdateInfo(
        current_version="7.0.0",
        latest_version="8.0.0",
        download_url="https://example.test/v8.zip",
        source="test",
    )

    worker, new_root = updater.prepare(info)

    assert worker.is_file()
    assert (new_root / "src" / "wekker" / "__init__.py").is_file()
    assert "8.0.0" in (new_root / "pyproject.toml").read_text(encoding="utf-8")


def test_zip_slip_wordt_geweigerd(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../kwaad.txt", "nee")
    with pytest.raises(UpdateError):
        SoftwareUpdater._safe_extract(buf.getvalue(), tmp_path)


def test_release_api_fout_valt_terug_op_main(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WAKESYNC_UPDATE_ALLOW_BRANCH", "1")
    updater = SoftwareUpdater(
        "caspervv44/slim", current_version="7.0.0", project_root=tmp_path
    )

    def fake(url: str, _limit: int) -> bytes:
        if "/releases/latest" in url:
            raise UpdateError("updateserver gaf HTTP 403")
        if "/main/pyproject.toml" in url:
            return b'[project]\nname="wekker"\nversion="8.0.0"\n'
        raise AssertionError(url)

    monkeypatch.setattr(updater, "_request_bytes", fake)
    info = updater.check()
    assert info.available is True
    assert info.source == "GitHub main (ontwikkelkanaal)"


def test_stabiel_kanaal_gebruikt_geen_branch_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("WAKESYNC_UPDATE_ALLOW_BRANCH", raising=False)
    updater = SoftwareUpdater(
        "caspervv44/slim", current_version="7.0.0", project_root=tmp_path
    )

    def fake(url: str, _limit: int) -> bytes:
        if "/releases/latest" in url:
            raise UpdateError("updateserver gaf HTTP 404")
        raise AssertionError("stabiel kanaal mag geen branch opvragen")

    monkeypatch.setattr(updater, "_request_bytes", fake)
    with pytest.raises(UpdateError, match="geen stabiele WakeSync Release"):
        updater.check()
