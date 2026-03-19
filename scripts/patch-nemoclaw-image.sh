#!/bin/bash
# patch-nemoclaw-image.sh
# Builds a Jetson-compatible version of the NemoClaw cluster image and
# retags it so openshell uses it automatically.
#
# Also pins the image so Docker cannot replace it with a remote pull by
# removing the registry digest — openshell will then use the local image.
#
# Usage: bash scripts/patch-nemoclaw-image.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
DOCKERFILE="$REPO_ROOT/docker/cluster-jetson/Dockerfile"

ORIGINAL_IMAGE="ghcr.io/nvidia/openshell/cluster:0.0.10"
PATCHED_TAG="openshell-cluster-jetson:0.0.10"

echo "==> [1/4] Pulling original image (base for patch)..."
docker pull "$ORIGINAL_IMAGE"

echo "==> [2/4] Building patched image for Jetson..."
echo "          - switches iptables → legacy (flannel/kube-proxy)"
echo "          - disables K3s network-policy controller (kube-router won't start)"
docker build \
    --tag "$PATCHED_TAG" \
    --file "$DOCKERFILE" \
    "$REPO_ROOT/docker/cluster-jetson"

echo "==> [3/4] Retagging as original image name so openshell picks it up..."
docker tag "$PATCHED_TAG" "$ORIGINAL_IMAGE"

echo "==> [4/4] Removing remote digest to prevent silent overwrite by docker pull..."
# Docker uses the RepoDigests entry to decide whether a remote image differs
# from the local one.  Clearing it means 'docker pull' will fetch a new copy
# but only if the caller explicitly requests it; openshell's 'docker run'
# (without --pull=always) will use the local image as-is.
docker image inspect "$ORIGINAL_IMAGE" --format '{{range .RepoDigests}}{{.}}{{"\n"}}{{end}}' \
    | grep -v '^$' \
    | xargs -r docker rmi --no-prune 2>/dev/null || true

echo ""
echo "[OK] Patched image is active. Verify with:"
echo "     docker run --rm --entrypoint sh $ORIGINAL_IMAGE -c 'iptables --version && cat /etc/rancher/k3s/config.yaml'"
echo ""
echo "     Then run: openshell gateway start --name nemoclaw"
