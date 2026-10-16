#!/usr/bin/env bash
set -euo pipefail

# 只有受控发布工作流可以上传；本地构建脚本没有发布权限。
: "${IMAGE:?Missing image}" "${VERSION:?Missing version}" "${GITHUB_SHA:?Missing source revision}"
# 上传前显式拒绝不匹配的工作流与发布分支，避免权限检查依赖 Shell 的隐式退出规则。
if [[ "${GITHUB_ACTIONS:-}" != "true" || "${GITHUB_REF:-}" != "refs/heads/release" ]]; then
  printf '%s\n' 'Matching release workflow required' >&2
  exit 1
fi

for arch in amd64 arm64; do
  source="saga-server:build-${GITHUB_SHA}-${arch}"
  target="${IMAGE}:sha-${GITHUB_SHA}-${arch}"
  docker tag "$source" "$target"
  docker push "$target"
done
docker buildx imagetools create --tag "${IMAGE}:${VERSION}" \
  "${IMAGE}:sha-${GITHUB_SHA}-amd64" "${IMAGE}:sha-${GITHUB_SHA}-arm64"
docker buildx imagetools inspect --raw "${IMAGE}:${VERSION}" > version-manifest.json
python3 - <<'PY'
import json
with open('version-manifest.json') as source:
    manifests = json.load(source)['manifests']
assert sorted((item['platform']['os'], item['platform']['architecture']) for item in manifests) == [('linux', 'amd64'), ('linux', 'arm64')]
PY
