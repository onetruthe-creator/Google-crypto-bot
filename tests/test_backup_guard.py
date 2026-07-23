"""
Tests for sovereign.backup_guard

Run with:  python3 -m pytest tests/test_backup_guard.py -v
Or inline: python3 tests/test_backup_guard.py
"""

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

# Allow running from repo root without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent))

# Redirect backup root and audit log into a temp dir for tests.
_tmp = tempfile.mkdtemp(prefix="sovereign_test_")
os.environ["SOVEREIGN_BACKUP_ROOT"] = _tmp + "/backups"
os.environ["SOVEREIGN_AUDIT_LOG"] = _tmp + "/audit.jsonl"

import sovereign.backup_guard as bg  # noqa: E402 — must come after env vars

# Point the module at the temp dirs (env vars set before import, but reload
# the Path objects in case they were already resolved at import time).
bg.BACKUP_ROOT = Path(os.environ["SOVEREIGN_BACKUP_ROOT"])
bg.AUDIT_LOG = Path(os.environ["SOVEREIGN_AUDIT_LOG"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_file(directory: Path, name: str, content: bytes = b"original content") -> Path:
    p = directory / name
    p.write_bytes(content)
    return p


def _audit_entries(event: str | None = None) -> list[dict]:
    if not bg.AUDIT_LOG.exists():
        return []
    entries = []
    with open(bg.AUDIT_LOG) as f:
        for line in f:
            try:
                e = json.loads(line)
                if event is None or e.get("event") == event:
                    entries.append(e)
            except json.JSONDecodeError:
                pass
    return entries


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_backup_nonexistent_file_is_noop():
    """backup_file on a path that doesn't exist should return None silently."""
    result = bg.backup_file("/tmp/this_file_does_not_exist_sovereign_test_xyz")
    assert result is None


def test_backup_creates_copy(tmp_path):
    original = _make_file(tmp_path, "agent.py", b"agent code v1")
    backup_path = bg.backup_file(original)

    assert backup_path is not None
    assert backup_path.exists()
    assert backup_path.read_bytes() == b"agent code v1"


def test_backup_preserves_hash(tmp_path):
    original = _make_file(tmp_path, "config.json", b'{"key": "value"}')
    backup_path = bg.backup_file(original)

    assert _sha256(original) == _sha256(backup_path)


def test_backup_logs_to_audit(tmp_path):
    before = len(_audit_entries("backup_created"))
    original = _make_file(tmp_path, "logged.py", b"some content")
    bg.backup_file(original)
    after = len(_audit_entries("backup_created"))

    assert after == before + 1
    entry = _audit_entries("backup_created")[-1]
    assert entry["original"] == str(original)
    assert "sha256" in entry
    assert "timestamp_utc" in entry


def test_backup_timestamp_in_filename(tmp_path):
    original = _make_file(tmp_path, "timestamped.py", b"v1")
    backup_path = bg.backup_file(original)

    # Filename should contain a timestamp like 2025-07-23T14-05-33Z
    assert "__" in backup_path.name
    assert "T" in backup_path.name


def test_multiple_backups_dont_collide(tmp_path):
    original = _make_file(tmp_path, "multi.py", b"version 1")
    b1 = bg.backup_file(original)

    original.write_bytes(b"version 2")
    b2 = bg.backup_file(original)

    assert b1 != b2
    assert b1.exists()
    assert b2.exists()
    assert b1.read_bytes() == b"version 1"
    assert b2.read_bytes() == b"version 2"


def test_safe_write_backs_up_then_overwrites(tmp_path):
    original = _make_file(tmp_path, "safe.py", b"old content")
    original_hash = _sha256(original)

    bg.safe_write(original, b"new content")

    # File should now have new content.
    assert original.read_bytes() == b"new content"

    # A backup of the old content should exist.
    backups = bg.list_backups(original)
    assert len(backups) == 1
    assert backups[0]["sha256"] == original_hash


def test_safe_write_new_file_no_backup(tmp_path):
    new_file = tmp_path / "brand_new.py"
    assert not new_file.exists()

    before = len(_audit_entries("backup_created"))
    bg.safe_write(new_file, b"fresh content")
    after = len(_audit_entries("backup_created"))

    assert new_file.read_bytes() == b"fresh content"
    assert after == before  # no backup needed for a new file


def test_safe_write_text(tmp_path):
    original = _make_file(tmp_path, "text.py", b"old")
    bg.safe_write_text(original, "new text content")
    assert original.read_text() == "new text content"


def test_list_backups_returns_sorted_history(tmp_path):
    original = _make_file(tmp_path, "history.py", b"v1")
    bg.backup_file(original)

    original.write_bytes(b"v2")
    bg.backup_file(original)

    backups = bg.list_backups(original)
    assert len(backups) == 2
    # Should be oldest-first.
    assert backups[0]["timestamp_utc"] < backups[1]["timestamp_utc"]


def test_restore_backup_recovers_old_content(tmp_path):
    original = _make_file(tmp_path, "restore_me.py", b"original content")
    bg.backup_file(original)

    original.write_bytes(b"corrupted or wrong content")

    restored_from = bg.restore_backup(original)

    assert original.read_bytes() == b"original content"
    assert restored_from.exists()


def test_restore_backup_logs_restore_event(tmp_path):
    original = _make_file(tmp_path, "restore_logged.py", b"data")
    bg.backup_file(original)
    original.write_bytes(b"changed")

    before = len(_audit_entries("restore_completed"))
    bg.restore_backup(original)
    after = len(_audit_entries("restore_completed"))

    assert after == before + 1


def test_restore_raises_when_no_backups(tmp_path):
    new_file = _make_file(tmp_path, "no_backup.py", b"data")
    try:
        bg.restore_backup(new_file)
        assert False, "Should have raised FileNotFoundError"
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Runner (for python3 tests/test_backup_guard.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile as _tf

    passed = 0
    failed = 0
    errors = []

    tests = [
        (name, fn)
        for name, fn in sorted(globals().items())
        if name.startswith("test_")
    ]

    for name, fn in tests:
        try:
            if "tmp_path" in fn.__code__.co_varnames:
                with _tf.TemporaryDirectory() as td:
                    fn(Path(td))
            else:
                fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {name}: {exc}")
            failed += 1
            errors.append((name, exc))

    print(f"\n{passed} passed, {failed} failed")
    if errors:
        sys.exit(1)
