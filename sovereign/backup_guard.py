"""
backup_guard.py — Sovereign Council write-safety layer

Rule: any write to an existing file must call backup_file() first.
The backup is timestamped, SHA-256 hashed, and logged to the audit log.
Nothing is ever silently overwritten.

Usage
-----
from sovereign.backup_guard import backup_file, safe_write

# Option A — manual
backup_file("/path/to/file.py")
# ... now safe to overwrite

# Option B — atomic helper
safe_write("/path/to/file.py", new_content_bytes)

# Option C — wrap any arbitrary write callable
guarded_write(my_write_fn, "/path/to/file.py", arg1, arg2)
"""

import hashlib
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Union

# ---------------------------------------------------------------------------
# Configuration (override via env vars before importing)
# ---------------------------------------------------------------------------

# Root directory where all backups are stored.
BACKUP_ROOT = Path(os.environ.get("SOVEREIGN_BACKUP_ROOT", Path.home() / ".sovereign" / "backups"))

# Audit log file location.
AUDIT_LOG = Path(os.environ.get("SOVEREIGN_AUDIT_LOG", Path.home() / ".sovereign" / "backup_audit.jsonl"))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _log(entry: dict) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _backup_path(original: Path, ts: str) -> Path:
    """
    Mirror the original's absolute path inside BACKUP_ROOT, with a timestamp
    suffix so multiple backups of the same file never collide.

    Example:
      original  → /home/user/rwa/app.py
      backup    → ~/.sovereign/backups/home/user/rwa/app.py__2025-07-23T14-05-33Z
    """
    relative = original.resolve().relative_to("/")
    dest_dir = BACKUP_ROOT / relative.parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    return dest_dir / f"{original.name}__{ts}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def backup_file(path: Union[str, Path]) -> Path | None:
    """
    Copy *path* to the backup vault before any write touches it.

    Returns the backup path on success, or None if the file did not exist
    (in which case no backup is needed and the function is a no-op).

    Raises RuntimeError if the backup copy itself fails — the caller should
    NOT proceed with the write if this raises.
    """
    path = Path(path).resolve()

    if not path.exists():
        return None  # new file, nothing to back up

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")
    dest = _backup_path(path, ts)

    try:
        shutil.copy2(path, dest)
    except Exception as exc:
        raise RuntimeError(
            f"backup_guard: failed to back up {path} → {dest}: {exc}"
        ) from exc

    original_hash = _sha256(path)
    backup_hash = _sha256(dest)

    if original_hash != backup_hash:
        dest.unlink(missing_ok=True)
        raise RuntimeError(
            f"backup_guard: hash mismatch after copy — aborting to protect {path}"
        )

    entry = {
        "event": "backup_created",
        "timestamp_utc": ts,
        "original": str(path),
        "backup": str(dest),
        "sha256": original_hash,
        "size_bytes": path.stat().st_size,
    }
    _log(entry)

    return dest


def safe_write(path: Union[str, Path], content: bytes, mode: str = "wb") -> None:
    """
    Write *content* to *path*, backing up any pre-existing file first.

    This is an atomic-ish write: content is written to a temp file in the
    same directory, then renamed over the target so a crash mid-write does
    not leave a partial file.
    """
    path = Path(path).resolve()
    backup_file(path)  # raises on failure, preventing any write

    tmp = path.with_suffix(path.suffix + ".sovereign_tmp")
    try:
        with open(tmp, mode) as f:
            f.write(content)
        tmp.rename(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    _log({
        "event": "safe_write_completed",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "path": str(path),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    })


def safe_write_text(path: Union[str, Path], text: str, encoding: str = "utf-8") -> None:
    """Convenience wrapper around safe_write for text content."""
    safe_write(path, text.encode(encoding))


def guarded_write(write_fn: Callable, path: Union[str, Path], *args, **kwargs):
    """
    Wrap an arbitrary write callable so the file at *path* is backed up first.

    Example:
        guarded_write(shutil.copy, src, dest)
        guarded_write(json.dump, data, open(dest, "w"))
    """
    backup_file(path)
    return write_fn(*args, **kwargs)


def list_backups(path: Union[str, Path]) -> list[dict]:
    """
    Return a list of all known backups for *path*, sorted oldest-first,
    by scanning the audit log.
    """
    path = str(Path(path).resolve())
    results = []
    if not AUDIT_LOG.exists():
        return results
    with open(AUDIT_LOG, encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("original") == path and entry.get("event") == "backup_created":
                results.append(entry)
    results.sort(key=lambda e: e.get("timestamp_utc", ""))
    return results


def restore_backup(path: Union[str, Path], backup_index: int = -1) -> Path:
    """
    Restore *path* from one of its backups (default: the most recent).

    *backup_index* follows Python list indexing (-1 = latest, 0 = oldest).
    The current file is itself backed up before the restore, so the operation
    is always reversible.
    """
    path = Path(path).resolve()
    backups = list_backups(path)
    if not backups:
        raise FileNotFoundError(f"No backups found for {path}")

    chosen = backups[backup_index]
    backup_path = Path(chosen["backup"])
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup file missing on disk: {backup_path}")

    # Back up the current state before restoring, so nothing is ever lost.
    backup_file(path)

    shutil.copy2(backup_path, path)

    _log({
        "event": "restore_completed",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "restored_to": str(path),
        "restored_from": str(backup_path),
        "sha256": _sha256(path),
    })

    return backup_path
