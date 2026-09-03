#!/usr/bin/env bash
# install_executable_alerts.sh — Deploy lb_executable_* modules and patch trade-alerts.
#
# Usage: bash scripts/install_executable_alerts.sh [--workspace DIR]
#
# What it does:
#   1. Detect workspace (default: ~/.openclaw/workspace)
#   2. Timestamped backup of bitunix_trade_alerts.py
#   3. Copy three SME modules into workspace/sovereign_mission_engine/
#   4. Run the patch script
#   5. Print SHA-256 manifest of every installed file
#
# AUTHORIZATION: NONE — read-only analysis system.
# Production relay is disabled until LADYBUG_EXECUTABLE_ALERTS_ENABLED=1.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WORKSPACE="${LADYBUG_WORKSPACE:-${HOME}/.openclaw/workspace}"
SME_SRC="${REPO_DIR}/sovereign_mission_engine"
SME_DST="${WORKSPACE}/sovereign_mission_engine"
SCRIPTS_SRC="${REPO_DIR}/scripts"
BACKUP_DIR="${WORKSPACE}/.backups/executable-alerts"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"

if [[ "$*" == *--workspace* ]]; then
  for arg in "$@"; do
    case $arg in
      --workspace) shift; WORKSPACE="$1"; shift ;;
    esac
  done
fi

echo "=== Ladybug Executable-Alert Install ==="
echo "Workspace : ${WORKSPACE}"
echo "Timestamp : ${TIMESTAMP}"
echo ""

# ── 1. Preflight ──────────────────────────────────────────────────────────────
TARGET_PY="${WORKSPACE}/sovereign_mission_engine/bitunix_trade_alerts.py"
if [[ ! -f "${TARGET_PY}" ]]; then
  echo "ERROR: bitunix_trade_alerts.py not found at ${TARGET_PY}" >&2
  exit 1
fi

# ── 2. Backup ─────────────────────────────────────────────────────────────────
# Only back up the ORIGINAL (unpatched) file. If it's already patched, skip the
# backup so we don't overwrite the clean backup with a patched copy.
mkdir -p "${BACKUP_DIR}"
BACKUP_FILE="${BACKUP_DIR}/bitunix_trade_alerts.${TIMESTAMP}.py"
if grep -q "try_deliver_executable" "${TARGET_PY}" 2>/dev/null; then
  echo "[BACKUP] SKIP — file already patched; preserving earlier clean backup"
  BACKUP_FILE="$(ls -1t "${BACKUP_DIR}"/bitunix_trade_alerts.*.py 2>/dev/null | head -1)"
  if [[ -z "${BACKUP_FILE}" ]]; then
    echo "WARNING: no prior backup found — manual rollback may not be possible" >&2
  else
    echo "[BACKUP] Using existing backup: ${BACKUP_FILE}"
    echo "         sha256=$(sha256sum "${BACKUP_FILE}" | awk '{print $1}')"
  fi
else
  cp -p "${TARGET_PY}" "${BACKUP_FILE}"
  echo "[BACKUP] ${BACKUP_FILE}"
  echo "         sha256=$(sha256sum "${BACKUP_FILE}" | awk '{print $1}')"
fi

# ── 3. Install SME modules ────────────────────────────────────────────────────
MODULES=(
  "lb_executable_validator.py"
  "lb_executable_formatter.py"
  "lb_executable_delivery.py"
)

echo ""
echo "[INSTALL] Copying SME modules..."
for mod in "${MODULES[@]}"; do
  src="${SME_SRC}/${mod}"
  dst="${SME_DST}/${mod}"
  if [[ ! -f "${src}" ]]; then
    echo "ERROR: source not found: ${src}" >&2
    exit 1
  fi
  cp -p "${src}" "${dst}"
  echo "  ${dst}"
done

# ── 4. Apply patch ────────────────────────────────────────────────────────────
echo ""
echo "[PATCH] Applying patch to bitunix_trade_alerts.py..."
python3 "${SCRIPTS_SRC}/patch_bitunix_trade_alerts_executable.py" \
  --target "${TARGET_PY}"

# ── 5. SHA-256 manifest ───────────────────────────────────────────────────────
echo ""
echo "[MANIFEST] sha256 checksums"
echo "PACKAGE: lb_executable_alerts-${TIMESTAMP}"
for mod in "${MODULES[@]}"; do
  f="${SME_DST}/${mod}"
  echo "  $(sha256sum "${f}" | awk '{print $1}')  ${f}"
done
echo "  $(sha256sum "${TARGET_PY}" | awk '{print $1}')  ${TARGET_PY} (patched)"
if [[ -n "${BACKUP_FILE}" && -f "${BACKUP_FILE}" ]]; then
  echo "  $(sha256sum "${BACKUP_FILE}" | awk '{print $1}')  ${BACKUP_FILE} (backup — rollback target)"
fi

# ── 6. Post-install validation ────────────────────────────────────────────────
echo ""
echo "[VALIDATE] Running post-install checks..."
python3 "${SCRIPTS_SRC}/validate_executable_alerts.py" --workspace "${WORKSPACE}" \
  || echo "[VALIDATE] Some checks failed — review output above."

echo ""
echo "=== Install complete ==="
echo "Production delivery is DISABLED."
echo "To enable: export LADYBUG_EXECUTABLE_ALERTS_ENABLED=1"
echo "To rollback: bash scripts/rollback_executable_alerts.sh"
