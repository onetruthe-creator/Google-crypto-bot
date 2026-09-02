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
VENV_DIR = WORKSPACE / ".venv"
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


def create_workspace() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    _ok(f"workspace: {WORKSPACE}")


def _venv_python() -> Path:
    for candidate in (VENV_DIR / "bin" / "python3", VENV_DIR / "bin" / "python"):
        if candidate.exists():
            return candidate
    sys.exit(f"venv python not found under {VENV_DIR}")


def setup_venv() -> None:
    if not VENV_DIR.exists():
        _step(f"creating virtual environment at {VENV_DIR}")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
        _ok("virtual environment created")
    else:
        _ok(f"virtual environment already exists: {VENV_DIR}")

    _step("installing Python dependencies into venv")
    pip = VENV_DIR / "bin" / "pip"
    subprocess.check_call([str(pip), "install", "--quiet"] + REQUIRED_PACKAGES)
    _ok(f"installed: {', '.join(REQUIRED_PACKAGES)}")


def copy_files() -> None:
    files = [
        PACKAGE_DIR / "ladybug_main.py",
    ]
    pkg_src = PACKAGE_DIR / "ladybug"
    pkg_dst = WORKSPACE / "ladybug"
    pkg_dst.mkdir(exist_ok=True)

    for f in files:
        shutil.copy2(f, WORKSPACE / f.name)

    for src in pkg_src.glob("*.py"):
        shutil.copy2(src, pkg_dst / src.name)

    # Write run_ladybug.sh pointing at the venv python
    sh = WORKSPACE / "run_ladybug.sh"
    sh.write_text(
        f"#!/usr/bin/env bash\n"
        f"set -euo pipefail\n"
        f"WORKSPACE={WORKSPACE}\n"
        f'exec "{VENV_DIR}/bin/python3" "$WORKSPACE/ladybug_main.py" --workspace "$WORKSPACE" "$@"\n'
    )
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
    vpy = _venv_python()
    result = subprocess.run(
        [str(vpy), str(WORKSPACE / "ladybug_main.py"), "--help"],
        capture_output=True,
    )
    if result.returncode != 0:
        sys.exit(f"verification failed:\n{result.stderr.decode()}")
    _ok("self-test passed")


def write_manifest() -> None:
    manifest = {
        "version": VERSION,
        "workspace": str(WORKSPACE),
        "venv": str(VENV_DIR),
        "installed_by": os.environ.get("USER", "unknown"),
    }
    with open(WORKSPACE / "ladybug_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    _ok("manifest written")


def main() -> None:
    print(f"\nLadybug silent-watchlist v{VERSION} installer")
    print("=" * 48)

    check_python()
    create_workspace()
    setup_venv()
    copy_files()
    install_config()
    install_crontab()
    verify()
    write_manifest()

    vpy = _venv_python()
    print("\nInstallation complete.")
    print(textwrap.dedent(f"""
        Workspace : {WORKSPACE}
        Venv      : {VENV_DIR}
        Config    : {WORKSPACE}/ladybug_config.yaml
        Alerts    : {WORKSPACE}/ladybug_alerts.jsonl

        Manual run:
          {vpy} {WORKSPACE}/ladybug_main.py build
          {vpy} {WORKSPACE}/ladybug_main.py monitor

        Or via shell wrapper:
          {WORKSPACE}/run_ladybug.sh build
          {WORKSPACE}/run_ladybug.sh monitor

        AUTHORIZATION: NONE — Ladybug is read-only and never places orders.
    """).strip())


if __name__ == "__main__":
    main()
