# Patched NemoClaw cluster image for Jetson Orin Nano (Tegra kernel 5.15.x)
#
# Problem: ghcr.io/nvidia/openshell/cluster:0.0.10 ships iptables in nf_tables
# mode. The Tegra kernel lacks nf_tables modules, so the embedded K3s
# network-policy controller panics immediately on startup.
#
# Fix: (1) disable K3s network-policy controller via config so kube-router
#      never runs, and (2) switch iptables to legacy as belt-and-suspenders
#      for flannel and kube-proxy.

FROM ghcr.io/nvidia/openshell/cluster:0.0.10

USER root

# Install iptables (ships both nft and legacy binaries) and switch all
# variants to legacy. Required because the Tegra kernel lacks nf_tables
# modules — every nft iptables call returns "No such file or directory".
RUN apt-get update && \
    apt-get install -y iptables && \
    update-alternatives --set iptables  /usr/sbin/iptables-legacy  && \
    update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy && \
    update-alternatives --set arptables /usr/sbin/arptables-legacy && \
    update-alternatives --set ebtables  /usr/sbin/ebtables-legacy  && \
    rm -rf /var/lib/apt/lists/*

# Verify legacy mode is active.
RUN iptables --version | grep -qi legacy || \
    (echo "[ERROR] iptables is still nf_tables" && exit 1)

# Disable K3s network-policy controller (kube-router) via K3s config file.
# NOTE: K3s does not read a K3S_ARG env var — the only supported ways to
# pass server flags are CLI args or this config file.
RUN mkdir -p /etc/rancher/k3s && \
    printf 'disable:\n  - network-policy\n' >> /etc/rancher/k3s/config.yaml
