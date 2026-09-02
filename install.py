#!/usr/bin/env python3
"""
Ladybug silent-watchlist installer.
Installs to the workspace directory with no sudo required.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

VERSION = "1.1.0"
WORKSPACE = Path.home() / ".openclaw" / "workspace"
PACKAGE_DIR = Path(__file__).parent
REQUIRED_PACKAGES = ["requests", "pyyaml"]
MIN_PYTHON = (3, 8)

CRON_BUILD   = "0 0 * * *"
CRON_MONITOR = "*/5 * * * *"
CRON_TAG     = "# ladybug-v1"


def _step(msg: str) -> None:
    print(f"  → {msg}")


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}", file=sys.stderr)


def check_python() -> None:
    if sys.version_info < MIN_PYTHON:
        sys.exit(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required, got {sys.version}")
    _ok(f"Python {sys.version.split()[0]}")


def install_packages() -> None:
    _step("installing Python dependencies")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--quiet", "--user"] + REQUIRED_PACKAGES
    )
    _ok(f"installed: {', '.join(REQUIRED_PACKAGES)}")


def create_workspace() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    _ok(f"workspace: {WORKSPACE}")


def copy_files() -> None:
    files = [
        PACKAGE_DIR / "ladybug_main.py",
        PACKAGE_DIR / "run_ladybug.sh",
    ]
    pkg_src = PACKAGE_DIR / "ladybug"
    pkg_dst = WORKSPACE / "ladybug"
    pkg_dst.mkdir(exist_ok=True)

    for f in files:
        shutil.copy2(f, WORKSPACE / f.name)

    for src in pkg_src.glob("*.py"):
        shutil.copy2(src, pkg_dst / src.name)

    sh = WORKSPACE / "run_ladybug.sh"
    sh.chmod(sh.stat().st_mode | 0o111)
    _ok(f"files copied to {WORKSPACE}")


def install_config() -> None:
    cfg_dst = WORKSPACE / "ladybug_config.yaml"
    if cfg_dst.exists():
        _ok("config already present — skipping")
        return
    shutil.copy2(PACKAGE_DIR / "config.example.yaml", cfg_dst)
    _ok(f"config installed: {cfg_dst}")


def _cron_lines() -> list[str]:
    sh = WORKSPACE / "run_ladybug.sh"
    return [
        f"{CRON_BUILD}   {sh} build   {CRON_TAG}\n",
        f"{CRON_MONITOR} {sh} monitor {CRON_TAG}\n",
    ]


def install_crontab() -> None:
    try:
        existing = subprocess.check_output(["crontab", "-l"], stderr=subprocess.DEVNULL).decode()
    except subprocess.CalledProcessError:
        existing = ""

    if CRON_TAG in existing:
        _ok("crontab entries already present")
        return

    new_crontab = existing.rstrip("\n") + "\n" + "".join(_cron_lines())
    proc = subprocess.run(["crontab", "-"], input=new_crontab.encode(), capture_output=True)
    if proc.returncode != 0:
        _fail(f"crontab install failed: {proc.stderr.decode()}")
        return
    _ok("crontab entries installed")


def verify() -> None:
    _step("running self-test")
    result = subprocess.run(
        [sys.executable, str(WORKSPACE / "ladybug_main.py"), "--help"],
        capture_output=True,
    )
    if result.returncode != 0:
        sys.exit(f"verification failed:\n{result.stderr.decode()}")
    _ok("self-test passed")


def write_manifest() -> None:
    manifest = {
        "version": VERSION,
        "workspace": str(WORKSPACE),
        "installed_by": os.environ.get("USER", "unknown"),
    }
    with open(WORKSPACE / "ladybug_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    _ok(f"manifest written")


def main() -> None:
    print(f"\nLadybug silent-watchlist v{VERSION} installer")
    print("=" * 48)

    check_python()
    install_packages()
    create_workspace()
    copy_files()
    install_config()
    install_crontab()
    verify()
    write_manifest()

    print("\nInstallation complete.")
    print(textwrap.dedent(f"""
        Workspace : {WORKSPACE}
        Config    : {WORKSPACE}/ladybug_config.yaml
        Alerts    : {WORKSPACE}/ladybug_alerts.jsonl

        Manual run:
          python3 {WORKSPACE}/ladybug_main.py build
          python3 {WORKSPACE}/ladybug_main.py monitor

        AUTHORIZATION: NONE — Ladybug is read-only and never places orders.
    """).strip())


if __name__ == "__main__":
    main()
