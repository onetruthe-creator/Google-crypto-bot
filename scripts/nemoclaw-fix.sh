#!/bin/bash
# ============================================================
# nemoclaw-fix.sh
# Full diagnostic & repair script for NemoClaw stack
# Issues addressed:
#   1. Port 18789 blocked by openclaw-gateway
#   2. mTLS certificate mismatch after pod restarts
#   3. telegram-bridge crashing
#   4. Stale Docker container / k3s state
# ============================================================
set -euo pipefail
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC}  $1"; }
err()  { echo -e "${RED}✗${NC} $1"; }
info() { echo -e "${BLUE}→${NC} $1"; }
echo ""
echo "============================================"
echo "  NemoClaw Full Repair Script"
echo "============================================"
echo ""
# ─── STEP 1: Free port 18789 ────────────────────────────────
echo "─── [1/6] Freeing port 18789 ───────────────"
PORT_PIDS=$(lsof -ti :18789 2>/dev/null || true)
if [ -n "$PORT_PIDS" ]; then
  echo "$PORT_PIDS" | xargs kill -9 2>/dev/null && ok "Killed processes on port 18789 (PIDs: $PORT_PIDS)" || warn "Could not kill all processes on 18789"
else
  ok "Port 18789 already free"
fi
# Kill any lingering openclaw-gateway processes
pkill -f "openclaw-gateway" 2>/dev/null && ok "Killed openclaw-gateway" || true
# Give it a moment to fully release
sleep 2
# Verify
if lsof -i :18789 &>/dev/null; then
  err "Port 18789 still in use — manual intervention needed"
  lsof -i :18789
  exit 1
else
  ok "Port 18789 confirmed free"
fi
echo ""
# ─── STEP 2: Kill stale telegram-bridge ─────────────────────
echo "─── [2/6] Stopping stale services ─────────"
pkill -f "telegram-bridge" 2>/dev/null && ok "Killed old telegram-bridge" || ok "No telegram-bridge running"
sleep 1
echo ""
# ─── STEP 3: Handle Docker container ────────────────────────
echo "─── [3/6] Resetting Docker container ───────"
if docker inspect openshell-cluster-nemoclaw &>/dev/null; then
  info "Stopping openshell-cluster-nemoclaw..."
  docker stop openshell-cluster-nemoclaw 2>/dev/null && ok "Container stopped" || warn "Container already stopped"
  docker rm openshell-cluster-nemoclaw 2>/dev/null && ok "Container removed" || warn "Container already removed"
else
  ok "No stale container found"
fi
echo ""
# ─── STEP 4: Verify environment ─────────────────────────────
echo "─── [4/6] Environment checks ───────────────"
# Docker running?
if docker info &>/dev/null; then
  ok "Docker daemon running"
else
  err "Docker is not running — start it first: sudo systemctl start docker"
  exit 1
fi
# Token set?
if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
  err "TELEGRAM_BOT_TOKEN is not set in environment"
  warn "Run: source ~/.bashrc"
  source ~/.bashrc 2>/dev/null || true
  if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
    err "Token still missing after sourcing .bashrc — cannot continue"
    exit 1
  else
    ok "Token loaded from .bashrc"
  fi
else
  TOKEN_LEN=${#TELEGRAM_BOT_TOKEN}
  if [ "$TOKEN_LEN" -lt 40 ]; then
    err "TELEGRAM_BOT_TOKEN looks too short ($TOKEN_LEN chars) — may be invalid"
    warn "Expected ~45-50 chars. Run: read -s -p 'New token: ' T && sed -i \"s/export TELEGRAM_BOT_TOKEN=.*/export TELEGRAM_BOT_TOKEN=\$T/\" ~/.bashrc && source ~/.bashrc"
  else
    ok "TELEGRAM_BOT_TOKEN set (${TOKEN_LEN} chars)"
  fi
fi
# openshell CLI present?
if command -v openshell &>/dev/null; then
  ok "openshell CLI found: $(openshell --version 2>/dev/null || echo 'version unknown')"
else
  err "openshell CLI not found in PATH"
  exit 1
fi
# nemoclaw present?
if command -v nemoclaw &>/dev/null; then
  ok "nemoclaw CLI found"
else
  err "nemoclaw not found — reinstall: npm install -g nemoclaw"
  exit 1
fi
echo ""
# ─── STEP 5: Run nemoclaw onboard ───────────────────────────
echo "─── [5/6] Running nemoclaw onboard ─────────"
info "This may take a few minutes..."
echo ""
if nemoclaw onboard; then
  ok "nemoclaw onboard completed successfully"
else
  err "nemoclaw onboard failed"
  warn "Check output above for errors"
  exit 1
fi
echo ""
# ─── STEP 6: Start services & verify ────────────────────────
echo "─── [6/6] Starting services ─────────────────"
sleep 3
nemoclaw start
sleep 5
echo ""
echo "─── Verification ────────────────────────────"
# Check telegram-bridge process
BRIDGE_PID=$(pgrep -f "telegram-bridge" 2>/dev/null || true)
if [ -n "$BRIDGE_PID" ]; then
  ok "telegram-bridge running (PID: $BRIDGE_PID)"
else
  err "telegram-bridge not running after start"
fi
# Check Docker container
if docker ps --format '{{.Names}}' | grep -q "openshell-cluster"; then
  ok "openshell cluster container running"
  docker ps --filter "name=openshell-cluster" --format "  Name: {{.Names}} | Status: {{.Status}}"
else
  err "openshell cluster container not found"
fi
# Check k3s pods
echo ""
info "Checking k3s pod status..."
sleep 5
docker exec openshell-cluster-nemoclaw kubectl get pods -A 2>/dev/null && ok "k3s pods listed" || warn "Could not list k3s pods (cluster may still be starting)"
# Connect sandbox
echo ""
info "Connecting to sandbox..."
sleep 5
if nemoclaw my-assistant connect; then
  ok "Sandbox connected successfully"
else
  warn "Sandbox connect failed — may need more startup time. Retry: nemoclaw my-assistant connect"
fi
echo ""
echo "============================================"
echo "  Repair complete. Summary:"
echo "============================================"
nemoclaw status
echo ""
echo "  Next steps:"
echo "  1. Send a test message to your Telegram bot"
echo "  2. If no response: nemoclaw my-assistant logs --follow"
echo "  3. Monitor: openshell term"
echo "============================================"
echo ""
