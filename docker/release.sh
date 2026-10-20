#!/usr/bin/env bash
set -euo pipefail

description='Saga 协调服务：新增流程无需重启，多注册中心、持久恢复、幂等与补偿。'

# 业务作用: 拒绝缺少发布证据或内容不一致的操作，阻止后续外部写入。
# 参数说明:
# - message: 可公开的拒绝原因，不包含认证材料。
# 返回: 输出原因并以非零状态结束。
fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

# 业务作用: 将镜像发布权限限定在 release 分支的受控工作流内。
# 参数说明: 无。
# 返回: 上下文有效时继续，否则停止发布。
require_release() {
  # 本地环境或其它分支不能借用发布凭据修改公共镜像入口。
  if [[ "${GITHUB_ACTIONS:-}" != true || "${GITHUB_REF:-}" != refs/heads/release ]]; then
    fail 'Release workflow required'
  fi
}

# 业务作用: 从 Cargo manifest 读取可用于公开镜像标签的软件版本。
# 参数说明: 无。
# 返回: 设置 version；非稳定版本或无法读取 manifest 时停止。
read_version() {
  version="$(cargo metadata --locked --no-deps --format-version 1 |
    jq -er '.packages[] | select(.name == "saga-server") | .version')"
  if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    fail 'Stable version required'
  fi
}

# 业务作用: 限定镜像身份和目标仓库，避免未确认的摘要进入发布步骤。
# 参数说明: 无。
# 返回: 两个平台摘要及命名空间有效时继续，否则停止。
check_inputs() {
  local digest
  for digest in "${AMD64_CONFIG_DIGEST:-}" "${ARM64_CONFIG_DIGEST:-}"; do
    if [[ ! "$digest" =~ ^sha256:[a-f0-9]{64}$ ]]; then
      fail 'Invalid config digest'
    fi
  done
  if [[ "${HUB_NAMESPACE:-}" != nasaruntime ]]; then
    fail 'Docker Hub documentation and namespace must agree'
  fi
}

# 业务作用: 确认维护分支和发布分支共同指向本次工作流源码。
# 参数说明: 无。
# 返回: 两个分支均匹配 GITHUB_SHA 时继续，缺失或不一致时停止。
check_branches() {
  local branch ref
  for branch in master release; do
    ref="$(gh api "repos/${GITHUB_REPOSITORY}/git/ref/heads/${branch}")"
    # 分支证据不一致时不能继续，否则公开内容可能来自未经选定的提交。
    jq -e --arg sha "$GITHUB_SHA" '.object.sha == $sha' <<< "$ref" > /dev/null ||
      fail "${branch} has a different revision"
  done
}

# 业务作用: 将软件版本绑定到不可混用的 Git 提交，支持轻量标签和附注标签。
# 参数说明: 无。
# 返回: 设置 image_sha；版本标签不存在或不指向提交时停止。
read_tag() {
  local object
  object="$(gh api "repos/${GITHUB_REPOSITORY}/git/ref/tags/${version}" | jq -e '.object')"
  if [[ "$(jq -r '.type' <<< "$object")" == tag ]]; then
    object="$(gh api "repos/${GITHUB_REPOSITORY}/git/tags/$(jq -er '.sha' <<< "$object")" |
      jq -e '.object')"
  fi
  jq -e '.type == "commit"' <<< "$object" > /dev/null ||
    fail 'Version tag must point to a commit'
  image_sha="$(jq -er '.sha' <<< "$object")"
}

# 业务作用: 确认指定源码已完成 release 分支的受信构建。
# 参数说明:
# - run_id: GitHub Build 工作流的运行 ID。
# - expected_sha: 该构建必须对应的提交。
# 返回: 构建来源和成功状态均匹配时继续，否则停止。
check_build() {
  local run_id="$1" expected_sha="$2" run
  if [[ ! "$run_id" =~ ^[0-9]+$ ]]; then
    fail 'Invalid build run ID'
  fi
  run="$(gh api "repos/${GITHUB_REPOSITORY}/actions/runs/${run_id}")"
  # 只接受固定工作流的成功构建，排除其它分支、事件或未完成的产物。
  jq -e --arg sha "$expected_sha" '
    .head_sha == $sha and .head_branch == "release" and
    (.event == "push" or .event == "workflow_dispatch") and
    .path == ".github/workflows/ci.yml" and
    .status == "completed" and .conclusion == "success"
  ' <<< "$run" > /dev/null || fail 'Successful matching release Build required'
}

# 业务作用: 在公开说明写入前校验 Docker Hub 的 UTF-8 长度预算。
# 参数说明: 无。
# 返回: 说明和简介非空且未超限时继续，否则停止。
check_overview() {
  local overview_bytes summary_bytes
  overview_bytes="$(wc -c < docker/README.md)"
  summary_bytes="$(printf '%s' "$description" | wc -c)"
  if ((overview_bytes == 0 || overview_bytes > 25000 || summary_bytes == 0 || summary_bytes > 100)); then
    fail 'Repository overview or summary exceeds its UTF-8 budget'
  fi
}

# 业务作用: 绑定两份镜像归档与授权摘要，并确认装载后的运行身份和内容。
# 参数说明: 无。
# 返回: 两个平台镜像均核对并装载成功；任一不一致时停止。
verify_images() {
  local arch archive tag entries config_path digest config image expected
  : "${VERSION:?Missing version}"
  for arch in amd64 arm64; do
    archive="image-archives/saga-server-${arch}.tar"
    tag="saga-server:build-${GITHUB_SHA}-${arch}"
    entries="$(tar -xOf "$archive" manifest.json)"
    jq -e --arg tag "$tag" 'length == 1 and .[0].RepoTags == [$tag]' <<< "$entries" > /dev/null ||
      fail 'Unexpected archive tags'
    config_path="$(jq -er '.[0].Config | select(type == "string" and length > 0)' <<< "$entries")"
    digest="$(tar -xOf "$archive" -- "$config_path" | sha256sum)"
    expected="$AMD64_CONFIG_DIGEST"
    if [[ "$arch" == arm64 ]]; then
      expected="$ARM64_CONFIG_DIGEST"
    fi
    # 对原始字节计算摘要，必须在 docker load 前确认归档属于本次授权内容。
    if [[ "sha256:${digest%% *}" != "$expected" ]]; then
      fail 'Archive differs from validated artifact'
    fi
    config="$(tar -xOf "$archive" -- "$config_path")"
    docker load --input "$archive"
    image="$(docker image inspect "$tag" | jq -e '.[0]')"
    jq -en --argjson image "$image" --argjson config "$config" \
      --arg arch "$arch" --arg sha "$GITHUB_SHA" --arg version "$VERSION" '
      $image.RootFS.Type == $config.rootfs.type and
      $image.RootFS.Layers == $config.rootfs.diff_ids and
      (["User", "Env", "Entrypoint", "Cmd", "WorkingDir", "Labels", "StopSignal", "ExposedPorts"] |
        all(.[]; . as $field | $image.Config[$field] == $config.config[$field])) and
      $image.Architecture == $arch and $image.Os == "linux" and
      $config.architecture == $arch and $config.os == "linux" and
      $image.Config.User == "10001:10001" and
      $image.Config.Entrypoint == ["/app/saga-server"] and
      $image.Config.Labels["org.opencontainers.image.revision"] == $sha and
      $image.Config.Labels["org.opencontainers.image.version"] == $version
    ' > /dev/null || fail 'Loaded image differs from the authorized archive or runtime identity'
  done
}

# 业务作用: 读取远端镜像清单，区分不存在与无法确认。
# 参数说明:
# - reference: 待核对的镜像标签或内容摘要。
# 返回: 存在时输出 JSON，仅 HTTP 404 输出 null；其它失败停止发布。
manifest() {
  local response status
  : "${IMAGE:?Missing image}"
  response="$(curl --silent --show-error --max-time 30 \
    --header "Authorization: Bearer ${registry_token}" \
    --header 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json' \
    --write-out $'\n%{http_code}' \
    "https://registry-1.docker.io/v2/${IMAGE}/manifests/${1}")" ||
    fail 'Registry request failed'
  status="${response##*$'\n'}"
  case "$status" in
    200)
      printf '%s' "${response%$'\n'*}" | jq -ce 'select(type == "object")'
      ;;
    404)
      printf 'null\n'
      ;;
    *)
      # 无法读取不代表标签不存在，必须停止以免覆盖无法确认的版本。
      fail "Registry preflight failed: HTTP ${status}"
      ;;
  esac
}

# 业务作用: 防止覆盖已公开的版本内容，并确认 latest 仅引用选定版本。
# 参数说明: 无。
# 返回: 设置 PUBLISH_VERSION；远端身份不一致或证据不足时停止。
registry_check() {
  local registry_token version_manifest latest arch existing entry_digest expected source_revision publish
  : "${IMAGE:?Missing image}" "${VERSION:?Missing version}"
  registry_token="$(curl --fail --silent --show-error --max-time 30 --get \
    --data-urlencode service=registry.docker.io \
    --data-urlencode "scope=repository:${IMAGE}:pull" \
    https://auth.docker.io/token | jq -er '.token | select(type == "string" and length > 0)')"
  printf '::add-mask::%s\n' "$registry_token"
  source_revision="${IMAGE_SOURCE_REVISION:-$GITHUB_SHA}"
  version_manifest="$(manifest "$VERSION")"
  if [[ "${REQUIRE_VERSION_PRESENT:-}" == true && "$version_manifest" == null ]]; then
    fail 'Published version is missing'
  fi
  if [[ "$version_manifest" != null ]]; then
    # 已有版本只能用于继续同一内容的发布，不允许替换公开版本。
    jq -e '[.manifests[] | [.platform.os, .platform.architecture]] | sort ==
      [["linux", "amd64"], ["linux", "arm64"]]' <<< "$version_manifest" > /dev/null ||
      fail 'Existing version platforms differ'
  fi
  for arch in amd64 arm64; do
    expected="$AMD64_CONFIG_DIGEST"
    if [[ "$arch" == arm64 ]]; then
      expected="$ARM64_CONFIG_DIGEST"
    fi
    if [[ "$version_manifest" != null ]]; then
      entry_digest="$(jq -er --arg arch "$arch" \
        '.manifests[] | select(.platform.architecture == $arch) | .digest' <<< "$version_manifest")"
      existing="$(manifest "$entry_digest")"
      jq -e --arg expected "$expected" '.config.digest == $expected' <<< "$existing" > /dev/null ||
        fail 'Existing version content differs; choose a new version'
    fi
    existing="$(manifest "sha-${source_revision}-${arch}")"
    jq -e --arg expected "$expected" '. == null or .config.digest == $expected' <<< "$existing" > /dev/null ||
      fail 'Existing architecture image differs'
  done
  if [[ "${VERIFY_LATEST:-}" == true ]]; then
    # 最后回读默认入口，避免其它构建的内容混入已确认的软件版本。
    latest="$(manifest latest)"
    jq -en --argjson latest "$latest" --argjson version "$version_manifest" '
      $latest != null and $version != null and $latest.manifests == $version.manifests
    ' > /dev/null || fail 'Latest content differs from version'
  fi
  publish=false
  if [[ "$version_manifest" == null ]]; then
    publish=true
  fi
  printf 'PUBLISH_VERSION=%s\n' "$publish" >> "$GITHUB_ENV"
}

# 业务作用: 在镜像身份确认后更新 Docker Hub 简介和说明，并回读完整内容。
# 参数说明: 无。
# 返回: 公开内容与本地一致时成功；认证、写入或回读失败时停止。
publish_overview() {
  local token result url
  : "${IMAGE:?Missing image}"
  check_overview
  token="$(jq -n '{identifier: env.HUB_USERNAME, secret: env.HUB_TOKEN}' |
    curl --fail --silent --show-error --max-time 30 \
      --header 'Content-Type: application/json' --data-binary @- \
      https://hub.docker.com/v2/auth/token |
    jq -er '.access_token | select(type == "string" and length > 0)')"
  printf '::add-mask::%s\n' "$token"
  url="https://hub.docker.com/v2/repositories/${IMAGE}/"
  # 版本内容由前序步骤确认后才更新公开说明；请求失败时不输出可能回显凭据的正文。
  jq -n --arg description "$description" --rawfile overview docker/README.md \
    '{description: $description, full_description: $overview}' |
    curl --fail --silent --show-error --max-time 30 --request PATCH \
      --header 'Content-Type: application/json' --header "Authorization: Bearer ${token}" \
      --data-binary @- --output /dev/null "$url"
  result="$(curl --fail --silent --show-error --max-time 30 \
    --header "Authorization: Bearer ${token}" "$url")"
  jq -e --arg description "$description" --rawfile overview docker/README.md \
    '.description == $description and .full_description == $overview' <<< "$result" > /dev/null ||
    fail 'Docker Hub overview or summary differs'
}

case "${1:-}" in
  check-overview)
    check_overview
    ;;
  package-version)
    require_release
    read_version
    printf 'version=%s\n' "$version" >> "$GITHUB_OUTPUT"
    ;;
  verify-source|verify-metadata)
    require_release
    read_version
    check_inputs
    check_branches
    read_tag
    if [[ "$1" == verify-source ]]; then
      # 镜像上传必须绑定当前源码标签，不能用旧标签发布新的分支内容。
      if [[ "$image_sha" != "$GITHUB_SHA" ]]; then
        fail 'Version tag must point to the published source'
      fi
      check_build "$BUILD_RUN_ID" "$GITHUB_SHA"
    else
      # 文档与镜像可来自不同提交，但各自都必须有对应 release 成功构建。
      check_build "$DOCUMENTATION_RUN_ID" "$GITHUB_SHA"
      check_build "$BUILD_RUN_ID" "$image_sha"
    fi
    check_overview
    printf 'IMAGE=nasaruntime/saga-server\nVERSION=%s\nIMAGE_SOURCE_REVISION=%s\n' \
      "$version" "$image_sha" >> "$GITHUB_ENV"
    ;;
  verify-images)
    require_release
    check_inputs
    verify_images
    ;;
  registry-check)
    require_release
    check_inputs
    registry_check
    ;;
  publish-overview)
    require_release
    publish_overview
    ;;
  *)
    fail 'Expected check-overview, package-version, verify-source, verify-metadata, verify-images, registry-check or publish-overview'
    ;;
esac
