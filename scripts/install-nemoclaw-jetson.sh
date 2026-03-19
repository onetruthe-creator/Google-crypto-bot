#!/bin/bash
# install-nemoclaw-jetson.sh
# End-to-end NemoClaw setup for Jetson Orin Nano.
# Run as a user with sudo privileges (not as root).
#
# Usage:
#   bash install-nemoclaw-jetson.sh
#
# What this script does:
#   1. Fixes iptables to legacy mode (required on Tegra 5.15 kernel)
#   2. Deploys K3s config that disables network-policy (avoids nf_tables crash)
#   3. Installs / restarts K3s
#   4. Starts the NemoClaw gateway via openshell

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# ── 1. iptables legacy fix ─────────────────────────────────────────────────
echo "==> [1/4] Applying iptables legacy fix for Jetson Tegra kernel..."
bash "$SCRIPT_DIR/fix-iptables-jetson.sh"

# ── 2. K3s config ─────────────────────────────────────────────────────────
echo "==> [2/4] Installing K3s config..."
sudo mkdir -p /etc/rancher/k3s
sudo cp "$REPO_ROOT/k3s/config.yaml" /etc/rancher/k3s/config.yaml
echo "[OK] K3s config written to /etc/rancher/k3s/config.yaml"

# ── 3. K3s install / restart ──────────────────────────────────────────────
echo "==> [3/4] Setting up K3s..."

if ! command -v k3s &>/dev/null; then
    echo "[INFO] K3s not found, installing..."
    # K3S_DISABLE_NETWORK_POLICY is also passed as an env var as belt-and-suspenders
    export INSTALL_K3S_EXEC="--disable-network-policy --flannel-backend=vxlan"
    curl -sfL https://get.k3s.io | sh -
else
    echo "[INFO] K3s already installed, restarting service to apply new config..."
    sudo systemctl restart k3s
fi

echo "[INFO] Waiting for K3s node to be ready..."
for i in $(seq 1 30); do
    if sudo k3s kubectl get nodes 2>/dev/null | grep -q " Ready"; then
        echo "[OK] K3s node is Ready."
        break
    fi
    echo "  ... waiting ($i/30)"
    sleep 5
done

# ── 4. Start NemoClaw gateway ─────────────────────────────────────────────
echo "==> [4/4] Starting NemoClaw gateway..."

if ! command -v openshell &>/dev/null; then
    echo "[ERROR] 'openshell' command not found. Is NemoClaw installed?"
    echo "        If you have the installer script, run it first, then re-run this script."
    exit 1
fi

openshell gateway start --name nemoclaw
echo "[OK] NemoClaw gateway 'nemoclaw' started successfully."
