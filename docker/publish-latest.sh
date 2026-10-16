#!/usr/bin/env bash
set -euo pipefail

# 版本镜像和公开说明均完成后才移动 latest，避免提前开放不完整的部署入口。
: "${IMAGE:?Missing image}" "${VERSION:?Missing version}"
# 未持有对应版本的发布上下文时必须停止，不能移动公共默认标签。
if [[ "${GITHUB_ACTIONS:-}" != "true" || "${GITHUB_REF:-}" != "refs/heads/release" ]]; then
  printf '%s\n' 'Matching release workflow required' >&2
  exit 1
fi

docker buildx imagetools create --tag "${IMAGE}:latest" "${IMAGE}:${VERSION}"
docker buildx imagetools inspect "${IMAGE}:${VERSION}"
docker buildx imagetools inspect "${IMAGE}:latest"
printf 'Image: %s:%s\nSource: %s\n' "$IMAGE" "$VERSION" "${IMAGE_SOURCE_REVISION:-$GITHUB_SHA}" >> "$GITHUB_STEP_SUMMARY"
