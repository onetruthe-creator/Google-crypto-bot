# Google-crypto-bot

## NemoClaw on Jetson Orin Nano — Setup Guide

This repo contains scripts to fix the K3s/iptables gateway container issue on **Jetson Orin Nano** (Tegra kernel 5.15.x) and start the **NemoClaw** gateway.

---

### Problem

The Tegra kernel (`5.15.x-tegra`) does not include `nf_tables` netfilter modules.
K3s's network-policy controller tries to use `nf_tables` iptables, which crashes with errors like:

```
Error: could not load NFTables subsystem
```

### Fix Overview

1. Switch iptables to **legacy mode** (uses `iptables-legacy`, no nf_tables needed)
2. Configure K3s to **disable network policies** and use the `vxlan` flannel backend
3. Start NemoClaw gateway via `openshell`

---

### Quick Start (via PuTTY / SSH into the Jetson)

```bash
# Clone the repo on your Jetson
git clone <this-repo-url>
cd Google-crypto-bot

# Run the all-in-one installer
bash scripts/install-nemoclaw-jetson.sh
```

### Manual Steps

**Step 1 — Fix iptables (run once)**
```bash
bash scripts/fix-iptables-jetson.sh
```

**Step 2 — Apply K3s config and restart**
```bash
sudo mkdir -p /etc/rancher/k3s
sudo cp k3s/config.yaml /etc/rancher/k3s/config.yaml
sudo systemctl restart k3s
```

**Step 3 — Start NemoClaw**
```bash
openshell gateway start --name nemoclaw
```

---

### Files

| File | Purpose |
|------|---------|
| `scripts/fix-iptables-jetson.sh` | Switches iptables to legacy mode on Tegra kernel |
| `scripts/install-nemoclaw-jetson.sh` | End-to-end setup: iptables + K3s + NemoClaw |
| `k3s/config.yaml` | K3s config with `disable-network-policy: true` and `flannel-backend: vxlan` |
