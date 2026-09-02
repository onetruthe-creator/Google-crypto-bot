#!/usr/bin/env python3
from __future__ import annotations
import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("ladybug")


def _load_deps() -> None:
    missing = []
    for pkg in ("requests", "yaml"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        sys.exit(f"Missing packages: {missing}. Run: pip3 install requests pyyaml")


def _find_config(workspace: Path) -> Path | None:
    candidate = workspace / "ladybug_config.yaml"
    return candidate if candidate.exists() else None


def cmd_build(args: argparse.Namespace) -> None:
    from ladybug.config import Config
    from ladybug.bitunix_client import BitunixClient
    from ladybug.watchlist import build_watchlist, save_watchlist

    cfg = Config(_find_config(Path(args.workspace)))
    client = BitunixClient(cfg["bitunix"]["base_url"], cfg["bitunix"]["timeout_seconds"])
    symbols = build_watchlist(client, cfg)
    if not symbols:
        logger.warning("watchlist is empty — check connectivity and volume filters")
        return
    save_watchlist(symbols, cfg.watchlist_file)
    logger.info("watchlist built: %d symbols → %s", len(symbols), cfg.watchlist_file)


def cmd_monitor(args: argparse.Namespace) -> None:
    from ladybug.config import Config
    from ladybug.bitunix_client import BitunixClient
    from ladybug.watchlist import load_watchlist
    from ladybug.state import StateManager
    from ladybug.monitor import run_monitor

    cfg = Config(_find_config(Path(args.workspace)))
    symbols = load_watchlist(cfg.watchlist_file)
    if not symbols:
        logger.info("watchlist empty — run 'build' first")
        return
    client = BitunixClient(cfg["bitunix"]["base_url"], cfg["bitunix"]["timeout_seconds"])
    state_mgr = StateManager(cfg.state_file)
    run_monitor(cfg, client, state_mgr, symbols)


def main() -> None:
    _load_deps()
    parser = argparse.ArgumentParser(description="Ladybug silent watchlist agent")
    parser.add_argument("--workspace", default=str(Path.home() / ".openclaw" / "workspace"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build", help="Build daily watchlist")
    sub.add_parser("monitor", help="Run one monitoring pass")
    args = parser.parse_args()
    {"build": cmd_build, "monitor": cmd_monitor}[args.command](args)


if __name__ == "__main__":
    main()
