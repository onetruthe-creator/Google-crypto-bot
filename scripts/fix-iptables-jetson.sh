#!/bin/bash
# fix-iptables-jetson.sh
# Fixes iptables compatibility on Jetson Orin Nano (Tegra kernel 5.15.x)
# The Tegra kernel lacks nf_tables modules, so iptables must use legacy mode.

set -e

echo "[INFO] Checking kernel and platform..."
KERNEL=$(uname -r)
echo "[INFO] Kernel: $KERNEL"

if ! echo "$KERNEL" | grep -qi "tegra"; then
    echo "[WARN] This script is intended for Jetson (Tegra) devices. Proceed with caution."
fi

echo "[INFO] Installing iptables and alternatives..."
sudo apt-get update -qq
sudo apt-get install -y iptables arptables ebtables

echo "[INFO] Switching to iptables-legacy mode..."
sudo update-alternatives --set iptables  /usr/sbin/iptables-legacy
sudo update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy
sudo update-alternatives --set arptables /usr/sbin/arptables-legacy
sudo update-alternatives --set ebtables  /usr/sbin/ebtables-legacy

echo "[INFO] Verifying..."
iptables --version | grep -i legacy \
    && echo "[OK] iptables is now in legacy mode." \
    || { echo "[ERROR] iptables legacy mode not set correctly."; exit 1; }
