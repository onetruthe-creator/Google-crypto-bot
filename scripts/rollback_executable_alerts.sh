#!/usr/bin/env bash
# rollback_executable_alerts.sh — Restore bitunix_trade_alerts.py from backup.
#
# Usage:
#   bash scripts/rollback_executable_alerts.sh [--workspace DIR] [--backup FILE]
#
# Without --backup, restores the most-recent backup in the backup directory.
# Prints the SHA-256 of the restored file.
#
# AUTHORIZATION: NONE — this script makes no exchange calls.
set -euo pipefail

WORKSPACE="${LADYBUG_WORKSPACE:-${HOME}/.openclaw/workspace}"
BACKUP_DIR="${WORKSPACE}/.backups/executable-alerts"
BACKUP_FILE=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --workspace) WORKSPACE="$2"; shift 2 ;;
    --backup)    BACKUP_FILE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

TARGET_PY="${WORKSPACE}/sovereign_mission_engine/bitunix_trade_alerts.py"

if [[ -z "${BACKUP_FILE}" ]]; then
  if [[ ! -d "${BACKUP_DIR}" ]]; then
    echo "ERROR: backup directory not found: ${BACKUP_DIR}" >&2
    exit 1
  fi
  BACKUP_FILE="$(ls -1t "${BACKUP_DIR}"/bitunix_trade_alerts.*.py 2>/dev/null | head -1)"
  if [[ -z "${BACKUP_FILE}" ]]; then
    echo "ERROR: no backup files found in ${BACKUP_DIR}" >&2
    exit 1
  fi
fi

if [[ ! -f "${BACKUP_FILE}" ]]; then
  echo "ERROR: backup not found: ${BACKUP_FILE}" >&2
  exit 1
fi

echo "=== Ladybug Executable-Alert Rollback ==="
echo "Restoring from: ${BACKUP_FILE}"
echo "Restoring to  : ${TARGET_PY}"

BEFORE_SHA="$(sha256sum "${TARGET_PY}" | awk '{print $1}')"
cp -p "${BACKUP_FILE}" "${TARGET_PY}"
AFTER_SHA="$(sha256sum "${TARGET_PY}" | awk '{print $1}')"

echo ""
echo "Before sha256: ${BEFORE_SHA}"
echo "After  sha256: ${AFTER_SHA}"
echo "Backup sha256: $(sha256sum "${BACKUP_FILE}" | awk '{print $1}')"

if [[ "${AFTER_SHA}" != "$(sha256sum "${BACKUP_FILE}" | awk '{print $1}')" ]]; then
  echo "ERROR: sha256 mismatch after copy" >&2
  exit 1
fi

echo ""
echo "=== Rollback complete ==="
