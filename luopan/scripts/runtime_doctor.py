#!/usr/bin/env python3
"""Diagnose the interpreter and optional Luopan validation dependencies."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
import platform
import shutil
import sys
from pathlib import Path


MINIMUM = (3, 10)
PACKAGES = {"yaml": "PyYAML", "jsonschema": "jsonschema", "markdown": "Markdown"}


def module_status(module: str, distribution: str) -> dict:
    available = importlib.util.find_spec(module) is not None
    version = None
    if available:
        try:
            version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            pass
    return {"available": available, "version": version}


def inspect_venv(path: Path) -> dict:
    config = path / "pyvenv.cfg"
    interpreter = path / "Scripts" / "python.exe"
    result = {
        "path": str(path),
        "exists": path.exists(),
        "config": str(config),
        "interpreter": str(interpreter),
        "interpreter_exists": interpreter.is_file(),
        "base_home": None,
        "base_exists": None,
    }
    if not config.exists():
        return result
    try:
        lines = config.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as exc:
        result["config_error"] = str(exc)
        return result
    for line in lines:
        if line.lower().startswith("home") and "=" in line:
            home = line.split("=", 1)[1].strip()
            result["base_home"] = home
            try:
                base = Path(home)
                result["base_exists"] = base.is_dir() and (base / "python.exe").is_file()
            except OSError as exc:
                result["base_exists"] = False
                result["base_error"] = str(exc)
            break
    return result


def command_probe(command: str | None, *args: str) -> dict:
    if not command:
        return {"path": None, "works": False, "detail": "not found"}
    import subprocess

    try:
        result = subprocess.run([command, *args], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"path": command, "works": False, "detail": str(exc)}
    detail = (result.stdout or result.stderr).strip().splitlines()
    return {"path": command, "works": result.returncode == 0, "detail": detail[0] if detail else f"exit {result.returncode}"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--venv", action="append", default=[], help="venv directory to inspect")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    report = {
        "python": {
            "executable": sys.executable,
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "supported": sys.version_info >= MINIMUM,
            "prefix": sys.prefix,
            "base_prefix": sys.base_prefix,
        },
        "commands": {
            "python": command_probe(shutil.which("python"), "--version"),
            "py": command_probe(shutil.which("py"), "--version"),
            "uv": command_probe(shutil.which("uv"), "--version"),
        },
        "dependencies": {module: module_status(module, distribution) for module, distribution in PACKAGES.items()},
        "environment": {
            "PYTHONUTF8": os.getenv("PYTHONUTF8"),
            "PYTHONDONTWRITEBYTECODE": os.getenv("PYTHONDONTWRITEBYTECODE"),
        },
        "venvs": [inspect_venv(Path(item)) for item in args.venv],
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        python = report["python"]
        print(f"Python {python['version']} at {python['executable']} - {'supported' if python['supported'] else 'unsupported'}")
        for module, status in report["dependencies"].items():
            print(f"{PACKAGES[module]}: {status['version'] or 'missing'}")
        for name, status in report["commands"].items():
            state = "works" if status["works"] else "broken/missing"
            print(f"command {name}: {state} ({status['path'] or 'not found'}; {status['detail']})")
        for venv in report["venvs"]:
            healthy = venv["base_exists"] and venv["interpreter_exists"] and not venv.get("config_error")
            state = "missing" if not venv["exists"] else ("healthy" if healthy else "broken")
            print(f"venv {venv['path']}: {state} ({venv['base_home'] or 'unknown base'})")

    return 0 if report["python"]["supported"] and all(item["available"] for item in report["dependencies"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
