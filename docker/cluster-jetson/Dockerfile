# Patched NemoClaw cluster image for Jetson Orin Nano (Tegra kernel 5.15.x)
#
# Problem: ghcr.io/nvidia/openshell/cluster:0.0.10 ships iptables in nf_tables
# mode. The Tegra kernel lacks nf_tables modules, so the embedded K3s
# network-policy controller panics immediately on startup.
#
# Fix: switch iptables/ip6tables to legacy mode inside the container.

FROM ghcr.io/nvidia/openshell/cluster:0.0.10

# Switch to iptables-legacy.
# Try update-alternatives first (Debian/Ubuntu); fall back to direct symlink.
RUN set -e; \
    if update-alternatives --set iptables  /usr/sbin/iptables-legacy  2>/dev/null && \
       update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy 2>/dev/null; then \
        echo "[OK] switched via update-alternatives"; \
    elif [ -x /usr/sbin/iptables-legacy ]; then \
        ln -sf /usr/sbin/iptables-legacy  /usr/sbin/iptables; \
        ln -sf /usr/sbin/ip6tables-legacy /usr/sbin/ip6tables; \
        echo "[OK] switched via symlink"; \
    else \
        echo "[INFO] iptables-legacy not found, installing..."; \
        apt-get update -qq && \
        apt-get install -y --no-install-recommends iptables && \
        update-alternatives --set iptables  /usr/sbin/iptables-legacy && \
        update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy && \
        rm -rf /var/lib/apt/lists/*; \
    fi

# Verify
RUN iptables --version | grep -i legacy || \
    (echo "[ERROR] iptables legacy switch failed" && exit 1)
