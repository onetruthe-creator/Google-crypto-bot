# Patched NemoClaw cluster image for Jetson Orin Nano (Tegra kernel 5.15.x)
#
# Problem: ghcr.io/nvidia/openshell/cluster:0.0.10 ships iptables in nf_tables
# mode. The Tegra kernel lacks nf_tables modules, so the embedded K3s
# network-policy controller panics immediately on startup.
#
# Fix: switch iptables/ip6tables to legacy mode inside the container.

FROM ghcr.io/nvidia/openshell/cluster:0.0.10

# Ensure iptables-legacy is available, then switch all iptables variants to it.
# Needed because the Tegra kernel (5.15.x) lacks nf_tables modules, so every
# iptables nft call returns "No such file or directory" and kube-router panics.
RUN set -e; \
    # Install iptables package which ships both nft and legacy binaries on Debian/Ubuntu. \
    if command -v apt-get >/dev/null 2>&1; then \
        apt-get update -qq && \
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends iptables && \
        rm -rf /var/lib/apt/lists/*; \
    fi; \
    # Switch via update-alternatives (preferred). \
    if [ -x /usr/sbin/iptables-legacy ]; then \
        update-alternatives --set iptables  /usr/sbin/iptables-legacy  2>/dev/null || \
            ln -sf /usr/sbin/iptables-legacy  /usr/sbin/iptables; \
        update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy 2>/dev/null || \
            ln -sf /usr/sbin/ip6tables-legacy /usr/sbin/ip6tables; \
        # Also fix arptables/ebtables if present. \
        [ -x /usr/sbin/arptables-legacy ] && \
            { update-alternatives --set arptables /usr/sbin/arptables-legacy 2>/dev/null || \
              ln -sf /usr/sbin/arptables-legacy /usr/sbin/arptables; } || true; \
        [ -x /usr/sbin/ebtables-legacy ] && \
            { update-alternatives --set ebtables /usr/sbin/ebtables-legacy 2>/dev/null || \
              ln -sf /usr/sbin/ebtables-legacy /usr/sbin/ebtables; } || true; \
        echo "[OK] switched iptables → legacy"; \
    else \
        echo "[WARN] iptables-legacy not found after install — image may use non-Debian base"; \
    fi

# Verify the switch worked.
RUN iptables --version && \
    iptables --version | grep -qi legacy || \
    (echo "[ERROR] iptables is still nf_tables — check container base OS" && exit 1)
