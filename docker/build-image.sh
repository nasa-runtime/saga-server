#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
docker buildx build --load \
  --file "$project_dir/docker/Dockerfile" \
  --tag "${SAGA_IMAGE:-saga-server:1.0.0}" "$@" "$project_dir"
