#!/usr/bin/env bash
# ZeroClaw installation script for NVIDIA Jetson (aarch64)
# Usage: bash install_zeroclaw_jetson.sh [--uninstall]
set -euo pipefail

ZEROCLAW_REPO="https://github.com/zeroclaw-labs/zeroclaw.git"
ZEROCLAW_BIN="$HOME/.cargo/bin/zeroclaw"
SERVICE_FILE="/etc/systemd/system/zeroclaw.service"

# ─── helpers ────────────────────────────────────────────────────────────────
info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*" >&2; }
die()   { echo "[ERROR] $*" >&2; exit 1; }

# ─── uninstall ───────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--uninstall" ]]; then
    info "Stopping and removing ZeroClaw service..."
    sudo systemctl stop zeroclaw  2>/dev/null || true
    sudo systemctl disable zeroclaw 2>/dev/null || true
    sudo rm -f "$SERVICE_FILE"
    sudo systemctl daemon-reload
    info "Removing binary..."
    rm -f "$ZEROCLAW_BIN"
    info "ZeroClaw uninstalled."
    exit 0
fi

# ─── detect arch ─────────────────────────────────────────────────────────────
ARCH=$(uname -m)
[[ "$ARCH" == "aarch64" ]] || warn "Expected aarch64 but got $ARCH — continuing anyway."

# ─── system dependencies ─────────────────────────────────────────────────────
info "Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y build-essential pkg-config curl git

# ─── rust / cargo ────────────────────────────────────────────────────────────
if ! command -v cargo &>/dev/null; then
    info "Installing Rust toolchain..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path
    source "$HOME/.cargo/env"
else
    info "Rust already installed: $(rustc --version)"
fi

export PATH="$HOME/.cargo/bin:$PATH"

# ─── build & install ZeroClaw ────────────────────────────────────────────────
info "Cloning ZeroClaw..."
TMP_DIR=$(mktemp -d)
git clone --depth 1 "$ZEROCLAW_REPO" "$TMP_DIR/zeroclaw"

info "Building (this may take a while on Jetson)..."
cd "$TMP_DIR/zeroclaw"

# Use memory-conservative build profile if RAM is tight (< 1.5 GB free)
FREE_RAM_MB=$(awk '/MemAvailable/ {printf "%d", $2/1024}' /proc/meminfo)
if (( FREE_RAM_MB < 1500 )); then
    warn "Low RAM detected (${FREE_RAM_MB} MB free). Using optimized-for-size build..."
    CARGO_PROFILE_RELEASE_OPT_LEVEL=s cargo build --release --locked
else
    cargo build --release --locked
fi

info "Installing ZeroClaw binary..."
cargo install --path . --force --locked

# ─── PATH persistence ────────────────────────────────────────────────────────
CARGO_ENV_LINE='export PATH="$HOME/.cargo/bin:$PATH"'
for RC in "$HOME/.bashrc" "$HOME/.profile"; do
    if [[ -f "$RC" ]] && ! grep -qF '.cargo/bin' "$RC"; then
        echo "$CARGO_ENV_LINE" >> "$RC"
    fi
done

# ─── verify ──────────────────────────────────────────────────────────────────
info "Verifying installation..."
zeroclaw --version
zeroclaw doctor || true   # non-fatal; may need API key first

# ─── optional: systemd auto-start ────────────────────────────────────────────
read -rp "Enable ZeroClaw as a systemd service? [y/N] " REPLY
if [[ "${REPLY,,}" == "y" ]]; then
    CURRENT_USER=$(whoami)
    info "Creating $SERVICE_FILE ..."
    sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=ZeroClaw AI Agent Runtime
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$HOME
ExecStart=$ZEROCLAW_BIN run
Restart=on-failure
RestartSec=5
Environment=PATH=$HOME/.cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable zeroclaw
    sudo systemctl start zeroclaw
    info "Service started. Check status with: sudo systemctl status zeroclaw"
fi

# ─── cleanup ─────────────────────────────────────────────────────────────────
rm -rf "$TMP_DIR"

info "Done! ZeroClaw is installed at $ZEROCLAW_BIN"
info ""
info "Next steps:"
info "  1. Reload your shell:   source ~/.bashrc"
info "  2. Add your API key:    zeroclaw onboard --api-key <KEY> --provider openrouter --model openrouter/free"
info "  3. Test it:             zeroclaw agent -m 'Hello!'"
