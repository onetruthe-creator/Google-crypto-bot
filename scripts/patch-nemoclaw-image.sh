#!/bin/bash
# patch-nemoclaw-image.sh
# Builds a Jetson-compatible version of the NemoClaw cluster image and
# retags it so openshell uses it automatically.
#
# Usage: bash scripts/patch-nemoclaw-image.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
DOCKERFILE="$REPO_ROOT/docker/cluster-jetson/Dockerfile"

ORIGINAL_IMAGE="ghcr.io/nvidia/openshell/cluster:0.0.10"
PATCHED_TAG="openshell-cluster-jetson:0.0.10"

echo "==> [1/3] Pulling original image..."
docker pull "$ORIGINAL_IMAGE"

echo "==> [2/3] Building patched image for Jetson (iptables-legacy)..."
docker build \
    --tag "$PATCHED_TAG" \
    --file "$DOCKERFILE" \
    "$REPO_ROOT/docker/cluster-jetson"

echo "==> [3/3] Retagging as original image name so openshell uses it..."
docker tag "$PATCHED_TAG" "$ORIGINAL_IMAGE"

echo ""
echo "[OK] Done. openshell will now use the Jetson-patched image."
echo "     Run: openshell gateway start --name nemoclaw"
