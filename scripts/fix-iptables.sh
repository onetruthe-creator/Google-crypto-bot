#!/bin/sh
# Fix iptables backend compatibility issue.
#
# iptables v1.8+ defaults to the nf_tables backend, but many container
# environments (k3s, kind, Docker-in-Docker) only have the legacy xtables
# backend available. When nf_tables rules cannot be inserted the kube-router
# network-policy controller panics, which prevents proper pod networking and
# causes CoreDNS to be unreachable – manifesting as:
#
#   dial tcp: lookup registry: Try again
#
# This script switches every iptables variant to the legacy backend before k3s
# or any Kubernetes component starts.

set -e

for cmd in iptables iptables-restore iptables-save ip6tables ip6tables-restore ip6tables-save; do
    legacy="/usr/sbin/${cmd}-legacy"
    if [ -x "$legacy" ]; then
        update-alternatives --set "$cmd" "$legacy" 2>/dev/null || true
        echo "Switched $cmd -> $legacy"
    else
        echo "Warning: $legacy not found, skipping"
    fi
done

echo "iptables legacy mode configured successfully"
