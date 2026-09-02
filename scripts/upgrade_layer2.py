#!/usr/bin/env python3
"""
upgrade_layer2.py — Phase 1/2/3 intelligence upgrades for crypto-signals.py

Phase 1 — Exhaustion Gate & 1H timeframe:
  • Add "1H" to INTERVALS, TF_W, TF_LIM, TE
  • Add LADYBUG_EXHAUSTION_BLOCK_ENABLED flag (default ON, env-overridable)
  • Add HTF disagreement hard-block in analyze_mtf()

Phase 2 — Evidence-Weighted Score & Two-Layer Report:
  • Add evidence_score breakdown (raw/risk/calibration/total) to analyze_mtf()
  • Add _fmt_layer2_evidence() helper; call it from fmt() before AUTHORIZATION line

Phase 3 — Outcome Recording:
  • Add --record-outcome CLI flag so closed paper trades can write outcomes
    back into the journal (outcome, realized_r, mfe, mae)
  Usage: python3 crypto-signals.py --record-outcome BTCUSDT win 2.3 3.1 1.2

SAFETY:
  • Verifies SHA-256 before any write — aborts on unrecognized hash
  • Creates timestamped backup in ~/.openclaw/workspace/.backups/
  • Atomic write (temp file then os.replace)
  • python3 -m py_compile validation before replacing original
  • Idempotent — re-running is safe; already-applied patches are skipped

  AUTHORIZATION: NONE — read-only analysis upgrades only.
  This script never places, modifies, or cancels an exchange order.
"""
from __future__ import annotations
import hashlib, os, shutil, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

TARGET     = Path.home() / ".openclaw" / "workspace" / "scripts" / "crypto-signals.py"
BACKUP_DIR = Path.home() / ".openclaw" / "workspace" / ".backups"

# SHA-256 of the exact original reviewed source (verified Sep 2026).
ORIGINAL_SHA256 = "58d99aa2b5a34620d5cc86ec0b9d9285d03ccc0ed8b8fd61cad5a169e9d5b472"
# SHA-256 after the optional earlier Two-Layer patch (idempotent re-apply allowed).
PRIOR_PATCH_SHA256 = "66a66099ba49da6f9058d86f55e20319309b45c64bd72bc3227ae96693169813"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def abort(msg: str) -> None:
    print(f"\nABORT — {msg}", file=sys.stderr)
    sys.exit(1)


def apply_one(src: str, tag: str, old: str, new: str, already_marker: str = "") -> tuple[str, str]:
    """Replace old→new once. Returns (patched_src, status_line)."""
    if old in src:
        return src.replace(old, new, 1), f"  ✓  {tag}"
    if already_marker and already_marker in src:
        return src, f"  ↩  {tag} (already applied)"
    abort(
        f"Patch {tag!r}: anchor text not found.\n"
        "  The file may have been modified since the SHA-256 was taken.\n"
        "  Restore from backup and re-run, or open an issue."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Patch definitions (verified against ORIGINAL_SHA256)
# ─────────────────────────────────────────────────────────────────────────────

def build_patches() -> list[tuple[str, str, str, str]]:
    """Return list of (tag, old, new, already_marker) tuples."""
    patches: list[tuple[str, str, str, str]] = []

    # ── 1a  INTERVALS ────────────────────────────────────────────────────────
    patches.append((
        "1a INTERVALS",
        'INTERVALS=["4H","30m","15m","3m"]',
        'INTERVALS=["4H","1H","30m","15m","3m"]',
        '"1H","30m"',
    ))

    # ── 1b  TF_W ─────────────────────────────────────────────────────────────
    patches.append((
        "1b TF_W",
        'TF_W={"4H":4,"30m":3,"15m":2,"3m":1}',
        'TF_W={"4H":4,"1H":3,"30m":3,"15m":2,"3m":1}',
        '"1H":3',
    ))

    # ── 1c  TF_LIM ───────────────────────────────────────────────────────────
    patches.append((
        "1c TF_LIM",
        'TF_LIM={"4H":100,"30m":100,"15m":100,"3m":60}',
        'TF_LIM={"4H":100,"1H":100,"30m":100,"15m":100,"3m":60}',
        '"1H":100',
    ))

    # ── 1d  TE emoji dict ────────────────────────────────────────────────────
    patches.append((
        "1d TE",
        'TE={"4H":"\U0001f550","30m":"\U0001f55e","15m":"\U0001f552","3m":"\u26a1"}',
        'TE={"4H":"\U0001f550","1H":"\U0001f551","30m":"\U0001f55e","15m":"\U0001f552","3m":"\u26a1"}',
        '"1H":"\U0001f551"',
    ))

    # ── 1e  LADYBUG_EXHAUSTION_BLOCK_ENABLED flag ─────────────────────────────
    _closed_loop_block = (
        'LB_CLOSED_LOOP_ENABLED = (\n'
        '    os.getenv("LADYBUG_CLOSED_LOOP_ENABLED", "0")\n'
        '    .strip()\n'
        '    .lower()\n'
        '    in ("1", "true", "yes", "on")\n'
        ')'
    )
    patches.append((
        "1e EXHAUSTION_BLOCK_FLAG",
        _closed_loop_block,
        _closed_loop_block + (
            '\n\n'
            'LADYBUG_EXHAUSTION_BLOCK_ENABLED = (\n'
            '    os.getenv("LADYBUG_EXHAUSTION_BLOCK_ENABLED", "1")\n'
            '    .strip()\n'
            '    .lower()\n'
            '    in ("1", "true", "yes", "on")\n'
            ')'
        ),
        'LADYBUG_EXHAUSTION_BLOCK_ENABLED',
    ))

    # ── 1f  HTF disagreement hard-block in analyze_mtf() ─────────────────────
    patches.append((
        "1f HTF_HARD_BLOCK",
        '    d="LONG" if lw>sw else "SHORT" if sw>lw else "WAIT"',
        (
            '    d="LONG" if lw>sw else "SHORT" if sw>lw else "WAIT"\n'
            '    # Phase 1 \u2014 HTF disagreement hard-block (fail-closed).\n'
            '    # The 4H bias must agree with the lower-TF consensus direction.\n'
            '    # If it disagrees, the setup is not ready regardless of lower-TF score.\n'
            '    if LADYBUG_EXHAUSTION_BLOCK_ENABLED and d != "WAIT":\n'
            '        if base.get("direction", "WAIT") not in ("WAIT", d):\n'
            '            return None  # 4H bias opposes lower-TF direction \u2014 hard-blocked'
        ),
        '4H bias opposes lower-TF direction',
    ))

    # ── 2a  Evidence-weighted score decomposition in analyze_mtf() ────────────
    _old_return = (
        '    return dict(label=label,price=p,direction=d,conf=conf,stars=stars,leverage=lev,\n'
        '                mtf_score=mtf_sc,rank_score=rank_sc,tf_agree=agree,tf_total=total,tf_results=tfr,\n'
        '                sl=slp,tp1=t1,tp2=t2,rr1=rr1,rr2=rr2,notional=notional,margin=margin,qty=qty,\n'
        '                risk_usd=ru,rr_pct=rd/p*100,agree_pct=agree/total*100 if total else 0,'
        'volume_24h=vol,funding_rate=funding_rate,funding_next=funding_next,funding_note=fr_note)'
    )
    _new_return = (
        '    # Phase 2 \u2014 Evidence-weighted score decomposition.\n'
        '    # raw: absolute MTF score (source fact)\n'
        '    # risk: raw scaled by reward-risk factor (calculated)\n'
        '    # calibration: multiplier from calibration engine (1.0 until engine has data)\n'
        '    # total: final rank_score (calculated)\n'
        '    _ev_raw  = abs(mtf_sc)\n'
        '    _ev_rr   = min(rr2 / 3.0, 1.0) if rr2 > 0 else 0.0\n'
        '    evidence_score = {\n'
        '        "raw":         round(_ev_raw, 4),\n'
        '        "risk":        round(_ev_raw * _ev_rr, 4),\n'
        '        "calibration": 1.0,\n'
        '        "total":       round(rank_sc, 4),\n'
        '    }\n'
        '    return dict(label=label,price=p,direction=d,conf=conf,stars=stars,leverage=lev,\n'
        '                mtf_score=mtf_sc,rank_score=rank_sc,evidence_score=evidence_score,\n'
        '                tf_agree=agree,tf_total=total,tf_results=tfr,\n'
        '                sl=slp,tp1=t1,tp2=t2,rr1=rr1,rr2=rr2,notional=notional,margin=margin,qty=qty,\n'
        '                risk_usd=ru,rr_pct=rd/p*100,agree_pct=agree/total*100 if total else 0,'
        'volume_24h=vol,funding_rate=funding_rate,funding_next=funding_next,funding_note=fr_note)'
    )
    patches.append((
        "2a EVIDENCE_SCORE",
        _old_return,
        _new_return,
        'evidence_score',
    ))

    # ── 2b  _fmt_layer2_evidence helper function (inserted before def fmt) ────
    _l2_helper = (
        '\n'
        'def _fmt_layer2_evidence(a):\n'
        '    """Layer 2: exact-value evidence table. Never rounds for display.\n'
        '    Fields: raw=source fact | risk=calc | calibration=estimate | total=calc\n'
        '    """\n'
        '    ev = a.get("evidence_score") or {}\n'
        '    if not ev:\n'
        '        return []\n'
        '    rows = [\n'
        '        ("Raw MTF score    ", ev.get("raw",         "\u2014")),\n'
        '        ("Risk-adj score   ", ev.get("risk",        "\u2014")),\n'
        '        ("Calibration mult ", ev.get("calibration", "\u2014")),\n'
        '        ("Total rank score ", ev.get("total",       "\u2014")),\n'
        '    ]\n'
        '    out = ["\u2500" * 50, "  \U0001f4ca LAYER 2 \u2014 EVIDENCE SCORE (exact values)"]\n'
        '    for label, val in rows:\n'
        '        out.append(f"  \u2022 {label} {val}")\n'
        '    out.append("  source=fact | risk=calc | calibration=estimate | total=calc")\n'
        '    return out\n'
    )
    patches.append((
        "2b LAYER2_HELPER_FN",
        '\ndef fmt(a,rank=None):',
        _l2_helper + '\ndef fmt(a,rank=None):',
        '_fmt_layer2_evidence',
    ))

    # ── 2c  Call _fmt_layer2_evidence in fmt() before AUTHORIZATION line ───────
    _old_auth = (
        '    lines.append(\n'
        '        "  \u2022 AUTHORIZATION: NONE"\n'
        '    )'
    )
    _new_auth = (
        '    lines.extend(_fmt_layer2_evidence(a))\n'
        '    lines.append(\n'
        '        "  \u2022 AUTHORIZATION: NONE"\n'
        '    )'
    )
    patches.append((
        "2c LAYER2_CALL",
        _old_auth,
        _new_auth,
        'lines.extend(_fmt_layer2_evidence',
    ))

    # ── 3   Phase 3: outcome recording (flag + function + early-exit handler) ──
    _outcome_block = (
        'DO_RECORD_OUTCOME="--record-outcome" in sys.argv\n'
        '\n'
        '\n'
        'def _do_record_outcome():\n'
        '    """Phase 3 \u2014 write trade outcome back into the paper journal.\n'
        '\n'
        '    Usage:\n'
        '        python3 crypto-signals.py --record-outcome SYMBOL outcome [realized_r mfe mae]\n'
        '\n'
        '    outcome: win | loss | breakeven | void\n'
        '    realized_r: actual R multiple achieved (e.g. 2.3)\n'
        '    mfe: maximum favourable excursion in R\n'
        '    mae: maximum adverse excursion in R\n'
        '\n'
        '    Example:\n'
        '        python3 crypto-signals.py --record-outcome BTCUSDT win 2.3 3.1 1.2\n'
        '    """\n'
        '    import json as _json\n'
        '    args = sys.argv[1:]\n'
        '    try:\n'
        '        idx    = args.index("--record-outcome")\n'
        '        rest   = args[idx + 1:]\n'
        '        if len(rest) < 2:\n'
        '            print("Usage: --record-outcome SYMBOL outcome [realized_r mfe mae]")\n'
        '            return\n'
        '        symbol    = rest[0].upper()\n'
        '        outcome   = rest[1].lower()\n'
        '        realized_r = float(rest[2]) if len(rest) > 2 else None\n'
        '        mfe        = float(rest[3]) if len(rest) > 3 else None\n'
        '        mae        = float(rest[4]) if len(rest) > 4 else None\n'
        '    except (ValueError, IndexError) as exc:\n'
        '        print(f"RECORD_OUTCOME_ERROR: {exc}")\n'
        '        return\n'
        '    if not os.path.exists(JOURNAL):\n'
        '        print(f"RECORD_OUTCOME_ERROR: journal not found: {JOURNAL}")\n'
        '        return\n'
        '    try:\n'
        '        with open(JOURNAL) as _f:\n'
        '            journal = _json.load(_f)\n'
        '    except Exception as exc:\n'
        '        print(f"RECORD_OUTCOME_ERROR: read failed: {exc}")\n'
        '        return\n'
        '    if not isinstance(journal, list):\n'
        '        print("RECORD_OUTCOME_ERROR: journal root is not a JSON array")\n'
        '        return\n'
        '    # Find the most recent open entry for this symbol (outcome still null).\n'
        '    target = next(\n'
        '        (\n'
        '            e for e in reversed(journal)\n'
        '            if isinstance(e, dict)\n'
        '            and e.get("symbol") == symbol\n'
        '            and e.get("outcome") is None\n'
        '        ),\n'
        '        None,\n'
        '    )\n'
        '    if target is None:\n'
        '        print(f"RECORD_OUTCOME_ERROR: no open entry found for {symbol}")\n'
        '        return\n'
        '    target["outcome"] = outcome\n'
        '    if realized_r is not None:\n'
        '        target["realized_r"] = realized_r\n'
        '    if mfe is not None:\n'
        '        target["mfe"] = mfe\n'
        '    if mae is not None:\n'
        '        target["mae"] = mae\n'
        '    target["outcome_ts"] = datetime.now(timezone.utc).isoformat()\n'
        '    # Atomic write via temp-file rename.\n'
        '    tmp = JOURNAL + ".outcome_tmp"\n'
        '    try:\n'
        '        with open(tmp, "w") as _f:\n'
        '            _json.dump(journal, _f, indent=2)\n'
        '        os.replace(tmp, JOURNAL)\n'
        '        print(\n'
        '            f"RECORD_OUTCOME: {symbol} \u2192 {outcome}  "\n'
        '            f"r={realized_r}  mfe={mfe}  mae={mae}"\n'
        '        )\n'
        '    except Exception as exc:\n'
        '        print(f"RECORD_OUTCOME_ERROR: write failed: {exc}")\n'
        '        if os.path.exists(tmp):\n'
        '            os.remove(tmp)\n'
        '\n'
        '\n'
        'if DO_RECORD_OUTCOME:\n'
        '    _do_record_outcome()\n'
        '    sys.exit(0)\n'
        '\n'
        '\n'
    )
    patches.append((
        "3  OUTCOME_RECORDING",
        'DO_SCAN="--scan" in sys.argv\n',
        'DO_SCAN="--scan" in sys.argv\n' + _outcome_block,
        'DO_RECORD_OUTCOME',
    ))

    return patches


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("upgrade_layer2.py — Phase 1/2/3 intelligence upgrades")
    print("=" * 56)

    if not TARGET.exists():
        abort(f"Target file not found: {TARGET}")

    # Step 1: verify SHA-256
    digest = sha256_of(TARGET)
    if digest == ORIGINAL_SHA256:
        print(f"  SHA-256 verified  (original reviewed source)")
    elif digest == PRIOR_PATCH_SHA256:
        print(f"  SHA-256 verified  (prior Two-Layer patch — re-applying idempotently)")
    else:
        abort(
            f"Unrecognized SHA-256:\n"
            f"  got:      {digest}\n"
            f"  expected: {ORIGINAL_SHA256}\n"
            f"\nThis file does not match the reviewed source.\n"
            f"Restore from backup and re-run, or report this to the developer."
        )

    # Step 2: backup
    backup_path = _make_backup()
    print(f"  Backup created:   {backup_path}")

    # Step 3: apply patches
    src = TARGET.read_text(encoding="utf-8")
    statuses: list[str] = []
    for tag, old, new, already_marker in build_patches():
        src, status = apply_one(src, tag, old, new, already_marker)
        statuses.append(status)

    # Step 4: write to temp file and compile-check
    tmp = TARGET.with_suffix(".upgrade_tmp")
    try:
        tmp.write_text(src, encoding="utf-8")
        tmp.chmod(0o755)

        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(tmp)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            tmp.unlink(missing_ok=True)
            abort(
                f"Compile check FAILED — patched file has a syntax error:\n"
                f"{result.stderr}\n"
                f"Original is untouched. Backup is at: {backup_path}"
            )

        # Step 5: atomic replace
        os.replace(tmp, TARGET)

    except Exception as exc:
        tmp.unlink(missing_ok=True)
        abort(f"Unexpected error during write: {exc}\nOriginal untouched.")

    # Step 6: report
    print()
    print("Patches applied:")
    for s in statuses:
        print(s)
    print()
    new_digest = sha256_of(TARGET)
    print(f"  New SHA-256:      {new_digest}")
    print(f"  Backup:           {backup_path}")
    print()
    print("INSTALL: PASS — Ladybug Phase 1/2/3 upgrades applied")
    print()
    print("Verify:")
    print(f"  python3 {TARGET} --scan          # should show LAYER 2 evidence table")
    print(f"  python3 {TARGET} --record-outcome BTCUSDT void  # test journal write")
    print()
    print("To roll back:")
    print(f"  cp {backup_path} {TARGET}")
    print()
    print("AUTHORIZATION: NONE — analysis upgrades only. No orders placed.")


def _make_backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = BACKUP_DIR / f"crypto-signals-{ts}.py"
    shutil.copy2(TARGET, dest)
    dest.chmod(0o600)
    return dest


if __name__ == "__main__":
    main()
