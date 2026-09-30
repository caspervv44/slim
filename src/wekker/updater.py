"""Veilige, gecontroleerde software-updater voor WakeSync.

V8 installeert standaard uitsluitend een gepubliceerde GitHub Release. Branch-
updates zijn alleen beschikbaar als ``WAKESYNC_UPDATE_ALLOW_BRANCH=1`` expliciet
is gezet. De installatiehelper houdt een operatiejournal bij, bewaart de oude
broncode als kopie en accepteert de nieuwe versie pas na een aparte healthcheck.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import textwrap
import tomllib
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import zipfile

from wekker import __version__

log = logging.getLogger(__name__)

DEFAULT_REPOSITORY = "caspervv44/slim"
HTTP_TIMEOUT_SECONDS = 15
MAX_METADATA_BYTES = 512 * 1024
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    download_url: str
    source: str
    notes: str = ""
    sha256: str = ""

    @property
    def available(self) -> bool:
        return _version_tuple(self.latest_version) > _version_tuple(self.current_version)


def _version_tuple(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str):
        raise UpdateError("versie heeft een ongeldig formaat")
    match = re.search(r"(?<!\d)(\d+)(?:\.(\d+))?(?:\.(\d+))?", value.strip())
    if not match:
        raise UpdateError(f"ongeldige versie: {value!r}")
    return tuple(int(part or 0) for part in match.groups())  # type: ignore[return-value]


def _version_from_pyproject(raw: bytes) -> str:
    try:
        data = tomllib.loads(raw.decode("utf-8"))
        version = str(data["project"]["version"])
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        raise UpdateError("pyproject.toml bevat geen geldige projectversie") from exc
    _version_tuple(version)
    return version


class SoftwareUpdater:
    def __init__(
        self,
        repository: str | None = None,
        *,
        current_version: str = __version__,
        project_root: str | Path | None = None,
    ) -> None:
        self.repository = (
            repository or os.environ.get("WAKESYNC_GITHUB_REPO") or DEFAULT_REPOSITORY
        ).strip("/")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository):
            raise UpdateError("WAKESYNC_GITHUB_REPO moet 'eigenaar/repository' zijn")
        self.current_version = current_version
        self.project_root = Path(project_root or Path(__file__).resolve().parents[2]).resolve()
        self.allow_branch = os.environ.get("WAKESYNC_UPDATE_ALLOW_BRANCH") == "1"

    def _request_bytes(self, url: str, limit: int) -> bytes:
        req = Request(
            url,
            headers={
                "Accept": "application/vnd.github+json, application/json;q=0.9, */*;q=0.1",
                "User-Agent": f"WakeSync/{self.current_version}",
            },
            method="GET",
        )
        try:
            with urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as response:
                raw = response.read(limit + 1)
        except HTTPError as exc:
            raise UpdateError(f"updateserver gaf HTTP {exc.code}") from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise UpdateError(f"updateserver niet bereikbaar: {getattr(exc, 'reason', exc)}") from exc
        if len(raw) > limit:
            raise UpdateError("updatebestand is onverwacht groot")
        return raw

    def _release_info(self) -> UpdateInfo | None:
        url = f"https://api.github.com/repos/{self.repository}/releases/latest"
        try:
            raw = self._request_bytes(url, MAX_METADATA_BYTES)
        except UpdateError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpdateError("GitHub gaf ongeldige release-informatie") from exc
        if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
            return None

        tag = str(data.get("tag_name") or "").lstrip("vV")
        if not tag:
            return None
        _version_tuple(tag)

        assets = data.get("assets") if isinstance(data.get("assets"), list) else []
        download_url = ""
        checksum_url = ""
        version_token = tag.replace(".", "-")
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or "").lower()
            browser = str(asset.get("browser_download_url") or "")
            if name.endswith(".zip") and ("wakesync" in name or version_token in name):
                download_url = browser
                break
        if not download_url:
            # Een release-tag zipball is nog steeds vastgepinde releasecode;
            # er wordt dus nooit stil naar een bewegende branch uitgeweken.
            download_url = str(data.get("zipball_url") or "")
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or "").lower()
            if name.endswith((".sha256", "sha256.txt", "sha256sums")):
                checksum_url = str(asset.get("browser_download_url") or "")
                break

        if not download_url:
            return None

        sha256 = ""
        if checksum_url:
            try:
                checksum_text = self._request_bytes(checksum_url, 64 * 1024).decode(
                    "utf-8", errors="replace"
                )
                match = re.search(r"\b([0-9a-fA-F]{64})\b", checksum_text)
                if match:
                    sha256 = match.group(1).lower()
            except UpdateError:
                log.warning("release-checksum kon niet worden gelezen")

        return UpdateInfo(
            current_version=self.current_version,
            latest_version=tag,
            download_url=download_url,
            source="GitHub Release",
            notes=str(data.get("body") or "")[:2000],
            sha256=sha256,
        )

    def _branch_info(self) -> UpdateInfo | None:
        if not self.allow_branch:
            return None
        last_error: UpdateError | None = None
        for branch in ("main", "master"):
            try:
                raw = self._request_bytes(
                    f"https://raw.githubusercontent.com/{self.repository}/{branch}/pyproject.toml",
                    MAX_METADATA_BYTES,
                )
            except UpdateError as exc:
                last_error = exc
                continue
            version = _version_from_pyproject(raw)
            return UpdateInfo(
                current_version=self.current_version,
                latest_version=version,
                download_url=(
                    f"https://github.com/{self.repository}/archive/refs/heads/{branch}.zip"
                ),
                source=f"GitHub {branch} (ontwikkelkanaal)",
            )
        if last_error:
            raise last_error
        return None

    def check(self) -> UpdateInfo:
        release_error: UpdateError | None = None
        try:
            release = self._release_info()
        except UpdateError as exc:
            # Het stabiele kanaal faalt gesloten: een netwerk/API-fout mag nooit
            # stil overschakelen naar onbeoordeelde branchcode. Alleen het
            # expliciete ontwikkelkanaal mag dat.
            if not self.allow_branch:
                raise
            release = None
            release_error = exc

        if release is not None:
            return release

        branch = self._branch_info()
        if branch is not None:
            return branch

        if self.allow_branch:
            if release_error is not None:
                raise UpdateError(
                    f"geen bruikbare release of ontwikkelbranch gevonden; "
                    f"releasecontrole: {release_error}"
                ) from release_error
            raise UpdateError("geen bruikbare release of ontwikkelbranch gevonden")
        raise UpdateError(
            "geen stabiele WakeSync Release gevonden; publiceer eerst een GitHub Release"
        )

    @staticmethod
    def _safe_extract(archive: bytes, destination: Path) -> None:
        try:
            with zipfile.ZipFile(io.BytesIO(archive)) as zf:
                for info in zf.infolist():
                    member = PurePosixPath(info.filename)
                    if member.is_absolute() or ".." in member.parts:
                        raise UpdateError("update-archief bevat een onveilig pad")
                    mode = (info.external_attr >> 16) & 0o170000
                    if mode == 0o120000:
                        raise UpdateError("update-archief bevat een symlink")
                zf.extractall(destination)
        except zipfile.BadZipFile as exc:
            raise UpdateError("gedownloade update is geen geldige ZIP") from exc

    @staticmethod
    def _find_project_root(extracted: Path) -> Path:
        candidates = []
        if (extracted / "pyproject.toml").is_file():
            candidates.append(extracted)
        candidates.extend(
            item for item in extracted.iterdir()
            if item.is_dir() and (item / "pyproject.toml").is_file()
        )
        for candidate in candidates:
            if (candidate / "src" / "wekker" / "__init__.py").is_file():
                return candidate
        raise UpdateError("update bevat geen geldige WakeSync-projectstructuur")

    def prepare(self, info: UpdateInfo) -> tuple[Path, Path]:
        if not info.available:
            raise UpdateError("de geïnstalleerde versie is al actueel")
        if not self.project_root.joinpath("pyproject.toml").is_file():
            raise UpdateError("WakeSync-projectmap kon niet worden bevestigd")
        if not os.access(self.project_root, os.W_OK):
            raise UpdateError("de WakeSync-projectmap is niet schrijfbaar")

        work_dir = Path(tempfile.mkdtemp(prefix="wakesync-update-"))
        archive = self._request_bytes(info.download_url, MAX_ARCHIVE_BYTES)
        digest = hashlib.sha256(archive).hexdigest()
        if info.sha256 and digest != info.sha256.lower():
            raise UpdateError("SHA-256 van de release komt niet overeen")

        extracted = work_dir / "extracted"
        extracted.mkdir()
        self._safe_extract(archive, extracted)
        new_root = self._find_project_root(extracted)
        archive_version = _version_from_pyproject((new_root / "pyproject.toml").read_bytes())
        if _version_tuple(archive_version) != _version_tuple(info.latest_version):
            raise UpdateError(
                "versienummer van het update-archief komt niet overeen met de release"
            )

        worker = work_dir / "install_update.py"
        worker.write_text(_WORKER_SCRIPT, encoding="utf-8")
        return worker, new_root

    def launch_install(
        self,
        info: UpdateInfo,
        *,
        restart_args: list[str] | None = None,
        parent_pid: int | None = None,
        settings_path: str = "wekker-settings.json",
    ) -> subprocess.Popen:
        worker, new_root = self.prepare(info)
        restart_args = restart_args or [sys.executable, "-m", "wekker", "gui"]
        config = {
            "project_root": str(self.project_root),
            "new_root": str(new_root),
            "python": sys.executable,
            "restart_args": restart_args,
            "parent_pid": int(parent_pid or os.getpid()),
            "target_version": info.latest_version,
            "settings_path": settings_path,
        }
        config_path = worker.with_name("update-config.json")
        config_path.write_text(json.dumps(config), encoding="utf-8")
        return subprocess.Popen(
            [sys.executable, str(worker), str(config_path)],
            cwd=str(worker.parent),
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


_WORKER_SCRIPT = textwrap.dedent(r"""
    from __future__ import annotations
    import json, os, shutil, subprocess, sys, time
    from datetime import datetime, timezone
    from pathlib import Path

    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    project = Path(config["project_root"]).resolve()
    source = Path(config["new_root"]).resolve()
    python = config["python"]
    parent_pid = int(config["parent_pid"])
    restart_args = list(config["restart_args"])
    target_version = str(config["target_version"])
    settings_path = str(config.get("settings_path") or "wekker-settings.json")
    # Alleen voor geautomatiseerde rollbacktests. launch_install() zet deze
    # sleutel nooit; productie-updates kunnen hem dus niet per ongeluk activeren.
    test_fail_phase = str(config.get("_test_fail_phase") or "")
    log_path = project / "wakesync-update.log"
    status_path = project / ".wakesync-update-status.json"
    journal_path = project / ".wakesync-update-journal.json"

    targets = [
        "src", "tests", "docs", "deploy", "pyproject.toml",
        "README.md", ".gitignore", "CHANGELOG-v8.md",
    ]

    def log(message):
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")

    def write_json(path, data):
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def fail_if(phase):
        if test_fail_phase == phase:
            raise RuntimeError(f"gesimuleerde updatefout in fase {phase}")

    def parent_alive():
        try:
            os.kill(parent_pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    for _ in range(80):
        if not parent_alive():
            break
        time.sleep(0.25)

    backup_root = project / ".wakesync-backups"
    backup_root.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = backup_root / f"before-{target_version}-{stamp}"
    backup.mkdir()
    staging = project / ".wakesync-update-staging" / stamp
    staging.mkdir(parents=True)
    journal = {"target_version": target_version, "started": [], "completed": []}

    def backup_target(name):
        old = project / name
        if not old.exists():
            return
        dest = backup / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if old.is_dir():
            shutil.copytree(old, dest)
        else:
            shutil.copy2(old, dest)

    def stage_target(name):
        new = source / name
        if not new.exists():
            return False
        dest = staging / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if new.is_dir():
            shutil.copytree(new, dest)
        else:
            shutil.copy2(new, dest)
        return True

    def remove_path(path):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()

    try:
        write_json(status_path, {
            "status": "installing", "target_version": target_version,
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
        log(f"installatie WakeSync {target_version} gestart")

        # Fase 1: kopieer alles. De actieve broncode blijft volledig intact.
        for name in targets:
            backup_target(name)
            fail_if("backup")
            stage_target(name)
            fail_if("stage")

        # Fase 2: per target journalen vóór de eerste mutatie.
        for name in targets:
            staged = staging / name
            if not staged.exists():
                continue
            journal["started"].append(name)
            write_json(journal_path, journal)
            fail_if("journal")

            current = project / name
            remove_path(current)
            fail_if("remove")
            current.parent.mkdir(parents=True, exist_ok=True)
            if staged.is_dir():
                shutil.copytree(staged, current)
            else:
                shutil.copy2(staged, current)
            fail_if("copy")

            journal["completed"].append(name)
            write_json(journal_path, journal)

        fail_if("pip")
        pip = subprocess.run(
            [python, "-m", "pip", "install", "-e", "."],
            cwd=project, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=300,
        )
        log(pip.stdout[-12000:])
        if pip.returncode != 0:
            raise RuntimeError("pip-installatie van de nieuwe versie is mislukt")

        fail_if("health")
        health = subprocess.run(
            [python, "-m", "wekker", "healthcheck", "--settings", settings_path],
            cwd=project, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=45,
        )
        log("healthcheck: " + health.stdout[-4000:])
        if health.returncode != 0:
            raise RuntimeError("nieuwe WakeSync-versie faalde de healthcheck")

        write_json(status_path, {
            "status": "healthy", "target_version": target_version,
            "accepted_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            journal_path.unlink()
        except OSError:
            pass

        log(f"WakeSync {target_version} healthcheck geslaagd; herstart")
        fail_if("restart")
        subprocess.Popen(
            restart_args, cwd=project, start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    except Exception as exc:
        log(f"UPDATE MISLUKT: {exc}; gerichte rollback gestart")
        # Alleen targets die mogelijk zijn aangeraakt worden hersteld.
        for name in reversed(journal["started"]):
            current = project / name
            remove_path(current)
            saved = backup / name
            if saved.exists():
                current.parent.mkdir(parents=True, exist_ok=True)
                if saved.is_dir():
                    shutil.copytree(saved, current)
                else:
                    shutil.copy2(saved, current)
        try:
            subprocess.run(
                [python, "-m", "pip", "install", "-e", "."],
                cwd=project, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=300,
            )
        except Exception:
            pass
        write_json(status_path, {
            "status": "rolled_back", "target_version": target_version,
            "error": str(exc)[:500],
            "at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            subprocess.Popen(
                restart_args, cwd=project, start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
        raise
""")
