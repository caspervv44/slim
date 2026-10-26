#!/usr/bin/env python3
"""Gerichte update van WakeSync Premium 10.2.0 naar 10.2.1.

Standaard uitsluitend controleren. Pas --apply schrijft bronbestanden.
Oudere agendahotfixes, privébestanden en systeemkalibratie blijven onaangeraakt.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib

from wakesync_install_common import apply_transaction, restore_transaction

ROOT = Path(__file__).resolve().parents[1]
VERSION = "10.2.1"
PAYLOAD = ROOT / "updates/v10_2_1/payload"
BASES = ROOT / "updates/v10_2_1/bases"
MERGEABLE = {"src/wekker/gui/premium.py", "src/wekker/gui/premium_render.py"}


def normalized(data: bytes) -> bytes:
    return data.decode("utf-8").replace("\r\n", "\n").encode("utf-8")


def text_hash(data: bytes) -> str:
    return hashlib.sha256(normalized(data)).hexdigest()


def merge_premium_source(name: str, current: bytes, updated: bytes, old_hashes: set[str]) -> bytes:
    """Voeg uitsluitend niet-conflicterende veranderingen samen via Git.

    Git vergelijkt drie inhoudelijke versies:
    - basis: de oorspronkelijke WakeSync 10.2.0-code;
    - lokaal: de huidige GitHub-code (met eigen verbeteringen);
    - nieuw: dezelfde 10.2.0-code met de 10.2.1-aanpassingen.

    Bij een conflict retourneren we GEEN half gewijzigde broncode.
    """
    baseline = BASES / name
    if not baseline.is_file() or baseline.is_symlink():
        raise ValueError(f"Veilige 10.2.0-basis ontbreekt: {name}")
    original = baseline.read_bytes()
    if text_hash(original) not in old_hashes:
        raise ValueError(f"De referentieversie is niet vertrouwd: {name}")
    if text_hash(current) == text_hash(updated):
        return current
    if text_hash(current) == text_hash(original):
        # Identieke code; bewaar de bestaande stijl voor regelafbrekingen.
        merged = normalized(updated)
    else:
        with tempfile.TemporaryDirectory(prefix="wakesync-threeway-") as directory:
            folder = Path(directory)
            local_file = folder / "mijn-github.py"
            base_file = folder / "basis-10.2.0.py"
            update_file = folder / "update-10.2.1.py"
            local_file.write_bytes(normalized(current))
            base_file.write_bytes(normalized(original))
            update_file.write_bytes(normalized(updated))
            try:
                completed = subprocess.run(
                    ["git", "merge-file", "--stdout",
                     str(local_file), str(base_file), str(update_file)],
                    capture_output=True,
                    check=False,
                    timeout=25,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise ValueError(f"Git samenvoegen niet beschikbaar ({name}): {error}") from error
            if completed.returncode != 0:
                # Git merge-file returns 1+ on overlapping changes. Keep ALL files intact.
                raise ValueError(
                    f"{name}: wijzigingen overlappen met de update. "
                    "NIETS aangepast. Upload dit bestand voor een handmatige, gerichte samenvoeging."
                )
            merged = completed.stdout
    if b"<<<<<<<" in merged or b">>>>>>>" in merged or b"=======" in merged:
        raise ValueError(f"Onopgeloste conflictmarkeringen in {name}")
    try:
        source = merged.decode("utf-8")
        tree = ast.parse(source, filename=name)
    except (UnicodeError, SyntaxError) as error:
        raise ValueError(f"Samengevoegde code is ongeldig ({name}): {error}") from error
    # Controleer dat noodzakelijke 10.2.1-onderdelen na het samenvoegen bestaan.
    if name.endswith("/premium.py"):
        methods = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        required = {"_premium_open_system_page", "_premium_poll_focus"}
        if not required.issubset(methods):
            raise ValueError(f"De nieuwe schermfuncties ontbreken na samenvoegen: {name}")
    else:
        if '"settings","settings","software"' not in source or '"settings","settings","diagnostics"' not in source:
            raise ValueError("Software/Diagnose zijn na samenvoegen niet aangesloten.")
    # Windows-checkouts met CRLF blijven CRLF; gebruikersdiffs blijven leesbaar.
    if b"\r\n" in current and b"\n" not in current.replace(b"\r\n", b""):
        return merged.replace(b"\n", b"\r\n")
    return merged


def method_arity(method: ast.FunctionDef) -> tuple[int, int]:
    """Aantal verplichte en maximaal geaccepteerde positionele args, zonder self."""
    args = method.args.posonlyargs + method.args.args
    count = max(0, len(args) - 1)
    required = max(0, count - len(method.args.defaults))
    return required, count


def choose_routes(app_source: str) -> dict:
    """Zoek bestaande echte functies in TouchApp; voer geen projectcode uit."""
    tree = ast.parse(app_source)
    app = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TouchApp"), None)
    if app is None:
        raise ValueError("TouchApp ontbreekt in gui/app.py; geen aanpassingen.")
    methods = {n.name: n for n in app.body if isinstance(n, ast.FunctionDef)}
    section = methods.get("_show_settings_section")
    # Literalen uitsluitend in de sectiekeuze zelf; geen willekeurige woordmatch.
    section_strings = {
        n.value for n in ast.walk(section)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    } if section else set()
    results = {}
    options = {
        "software": ("_show_update_overlay", "_show_software_section", "_show_software",
                     "_show_software_overlay", "_open_update_overlay", "_show_updates"),
        "diagnostics": ("_show_diagnostics", "_show_diagnostics_section",
                        "_show_diagnostics_overlay", "_show_diagnose", "_open_diagnostics"),
    }
    sections = {"software": ("software", "updates"),
                "diagnostics": ("diagnostics", "diagnose", "diagnostic")}
    for key, choices in options.items():
        chosen = next((name for name in choices
                       if name in methods and method_arity(methods[name])[0] == 0
                       and not methods[name].args.kwonlyargs), None)
        if chosen:
            results[key] = {"method": chosen, "args": []}
            continue
        suitable = bool(section and method_arity(section)[0] <= 1 <= method_arity(section)[1])
        selected = next((name for name in sections[key] if name in section_strings), None)
        if suitable and selected:
            results[key] = {"method": "_show_settings_section", "args": [selected]}
            continue
        # Meer generieke sectiedispatchers: zoek bestaande aanroepen in TouchApp.
        calls = [
            n for n in ast.walk(app) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == "_show_settings_section"
            and len(n.args) == 1 and isinstance(n.args[0], ast.Constant)
            and n.args[0].value in sections[key]
        ]
        if suitable and calls:
            results[key] = {"method": "_show_settings_section", "args": [calls[0].args[0].value]}
            continue
        names = ", ".join(sorted(n for n in methods if n.startswith(("_show_", "_open_"))))
        raise ValueError(
            f"Geen aantoonbaar bestaande {key}-schermfunctie gevonden. "
            f"Geen broncode veranderd.\nBeschikbare schermfuncties: {names}"
        )
    return results


def updated_project(text: str) -> str:
    data = tomllib.loads(text)
    version = data.get("project", {}).get("version")
    if version not in {"10.2.0", VERSION}:
        raise ValueError(f"Onverwachte pyproject-versie: {version!r}")
    match = re.search(r"(?m)^\[project\]\s*$", text)
    if not match:
        raise ValueError("[project] ontbreekt.")
    start = match.end()
    endmatch = re.search(r"(?m)^\[", text[start:])
    end = start + endmatch.start() if endmatch else len(text)
    section = text[start:end]
    section, count = re.subn(
        r"""(?m)^version\s*=\s*['"]10\.2\.[01]['"]([ \t]*(?:#.*)?)$""",
        'version = "10.2.1"\\1', section,
    )
    if count != 1:
        raise ValueError("Onbekende version-opbouw in pyproject.toml.")
    text = text[:start] + section + text[end:]
    scripts = data.get("project", {}).get("scripts", {})
    if "wakesync" in scripts:
        if scripts["wakesync"] != "wekker.desktop:main":
            raise ValueError("Een ander wakesync-commando bestaat al; niet overschrijven.")
    else:
        heading = re.search(r"(?m)^\[project\.scripts\][ \t]*$", text)
        if heading:
            text = text[:heading.end()] + '\nwakesync = "wekker.desktop:main"' + text[heading.end():]
        else:
            text = text.rstrip() + '\n\n[project.scripts]\nwakesync = "wekker.desktop:main"\n'
    # Controleer dat de bijgewerkte metadata echt parsebaar is.
    final = tomllib.loads(text)
    if final["project"]["version"] != VERSION or final["project"]["scripts"]["wakesync"] != "wekker.desktop:main":
        raise ValueError("Controle van metadata mislukt.")
    return text


def build_plan(repo: Path, payload: Path = PAYLOAD) -> dict:
    repo = repo.resolve()
    manifest = json.loads((payload.parent / "manifest.json").read_text(encoding="utf-8"))
    for name in ("pyproject.toml", "src/wekker/__init__.py", "src/wekker/gui/app.py"):
        if not (repo / name).is_file():
            raise ValueError(f"Geen volledige bestaande WakeSync-repo: {name} ontbreekt.")
    app_source = (repo / "src/wekker/gui/app.py").read_text(encoding="utf-8")
    if "PremiumTouchApp" not in app_source:
        raise ValueError("De premium-interface is niet geactiveerd. Eerst v10.2.0 controleren.")
    routes = choose_routes(app_source)
    changes = {}

    def prepare(name: str, after: bytes) -> None:
        path = repo / name
        before = path.read_bytes() if path.exists() else None
        if path.is_symlink():
            raise ValueError(f"Symbolische link niet overschrijven: {name}")
        mode = path.stat().st_mode & 0o777 if before is not None else 0o644
        if before != after:
            changes[path] = (before, after, mode)

    for name, specification in manifest["files"].items():
        rel = Path(name)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("Ongeldig payloadpad.")
        incoming = (payload / name).read_bytes()
        if text_hash(incoming) != specification["new"]:
            raise ValueError(f"Beschadigd updatebestand: {name}")
        path = repo / name
        existing = path.read_bytes() if path.exists() else None
        allowed = set(specification["old"]) | {specification["new"]}
        if existing is not None and text_hash(existing) not in allowed:
            if name not in MERGEABLE:
                raise ValueError(
                    f"{name} is onverwacht aangepast. "
                    "Veiligheidsstop: geen bestaande bestanden overschrijven."
                )
            incoming = merge_premium_source(
                name, existing, incoming, set(specification["old"]),
            )
            print(f"Samengevoegd met jouw GitHub-wijzigingen: {name}")
        if existing is None and specification["old"]:
            raise ValueError(f"Vereist bestaand bestand ontbreekt: {name}")
        if name.endswith(".py"):
            compile(incoming, name, "exec")
        prepare(name, incoming)

    init_name = "src/wekker/__init__.py"
    initial = (repo / init_name).read_text(encoding="utf-8")
    updated, count = re.subn(
        r"""(?m)^__version__\s*=\s*['"]10\.2\.[01]['"]([ \t]*(?:#.*)?)$""",
        '__version__ = "10.2.1"\\1', initial,
    )
    if count != 1:
        raise ValueError("Bronversie is geen ondersteunde 10.2.0/10.2.1.")
    prepare(init_name, updated.encode("utf-8"))
    prepare("pyproject.toml", updated_project((repo / "pyproject.toml").read_text(encoding="utf-8")).encode("utf-8"))
    prepare("src/wekker/gui/settings_routes_v1021.py",
            ('"""Bestaande schermroutes, gecontroleerd door de 10.2.1-installer."""\n'
             + "ROUTES = " + json.dumps(routes, indent=2, ensure_ascii=False)
             + "\n").encode("utf-8"))
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true")
    action.add_argument("--check", action="store_true")
    action.add_argument("--restore", type=Path)
    args = parser.parse_args()
    try:
        if args.restore:
            restore_transaction(args.restore)
            print("Bronbestanden hersteld; installeer het pakket opnieuw met pip install -e .")
            return 0
        changes = build_plan(args.repo)
        for path in changes:
            print("Wijziging:", path.relative_to(args.repo.resolve()))
        if not args.apply:
            print("Compatibiliteit gecontroleerd. Niets gewijzigd; gebruik --apply voor installatie.")
            return 0
        marker = hashlib.sha256(str(args.repo.resolve()).encode()).hexdigest()[:12]
        manifest = apply_transaction(
            changes, Path.home() / ".local/share/wakesync-source-backups" / marker,
        )
        print("WakeSync 10.2.1 toegepast." if changes else "WakeSync 10.2.1 staat al goed.")
        if manifest:
            print("Herstelmanifest:", manifest)
        print("Daarna: python3 -m pip install -e .")
        print("Tests: python3 -m pytest -q tests/test_wakesync_v1021.py")
        print("Op de Pi: python3 tools/install_wakesync_desktop.py --install --autostart")
        print("Touchkalibratie, privéfeed, cache en agenda-hotfixes zijn niet gewijzigd.")
        return 0
    except (OSError, ValueError, SyntaxError, KeyError) as exc:
        print(f"Veiligheidsstop: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
