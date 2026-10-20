# 镜像构建与仓库维护

维护分支为 `master`，发布分支固定为 `release`。Git 版本标签与 `Cargo.toml` 中的软件版本一致，例如 `1.0.0`，不加 `v` 前缀。Build 工作流在 release 分支生成 `linux/amd64` 和 `linux/arm64` 镜像归档，不自动上传镜像。归档保留 3 天，过期后需要重新构建。

工作流通过 Bash 运行 `docker/release.sh`：Cargo 读取软件版本，`gh` 核对源码和构建来源，`tar`、`sha256sum` 与 Docker 核对镜像归档，`curl` 和 `jq` 处理仓库 API。镜像上传和 `latest` 更新分别由 `docker/publish-images.sh`、`docker/publish-latest.sh` 执行；这些发布入口要求 GitHub Actions 的 release 分支上下文。

GitHub Actions 使用以下仓库配置：

| 类型 | 名称 | 用途 |
| --- | --- | --- |
| Variable | `DOCKERHUB_USERNAME` | 有目标仓库推送及更新仓库说明权限的账号 |
| Variable（可选） | `DOCKERHUB_NAMESPACE` | 默认 `nasaruntime`，无需配置；与镜像名及文档一致 |
| Secret | `DOCKERHUB_TOKEN` | 上述账号的访问凭据，不写入源码、环境样例或日志 |

先在 Docker Hub 的 `nasaruntime` 命名空间创建 Public 仓库 `saga-server`，确保匿名拉取和仓库说明读取可用。当前流程同时推送镜像并更新仓库说明，使用个人访问令牌（PAT），权限选择 `Repo Read, Write, Delete`（`repo:admin`），账号需要具有目标仓库的管理权限。在 Docker Home 的头像菜单进入 Account settings → Personal access tokens → Generate new token 创建，生成后将值保存到 GitHub 仓库的 `DOCKERHUB_TOKEN` Secret。权限范围和创建步骤见 [Docker Token 权限说明](https://docs.docker.com/security/access-tokens/reference/)与[个人令牌指南](https://docs.docker.com/security/access-tokens/personal-access-tokens/)。

最终源码与镜像内容确认后，为该提交创建版本标签。在 release 分支手工运行 `Publish Docker image`，提供成功 Build 的 `build_run_id` 以及两个归档的 `amd64_config_digest`、`arm64_config_digest`。摘要采用 `sha256:` 格式，来自各归档实际配置文件。工作流核对 `master`、`release`、版本标签与构建提交相同，核对归档和装载后镜像身份，再上传这两个既有镜像。支持直接指向该提交的轻量标签或附注标签；标签缺失或指向其它提交时停止。

发布先生成明确软件版本的多架构标签，例如 `nasaruntime/saga-server:1.0.0`，回读内容并更新仓库说明后，再使 `latest` 指向该版本。已有版本指向不同内容时拒绝覆盖，需要选择新的软件版本；镜像仓库无法读取或内容无法确认时停止。不会在发布阶段重建镜像替换已核对的归档。

## 更新既有版本的仓库说明

镜像版本与 Git 版本标签固定发布来源。后续说明更新使用 `Update Docker repository metadata`，保持已有镜像和标签不变。先将文档提交到 master/release，并完成当前 release 的 Build；提供该次 `documentation_run_id`、版本标签对应的原 `build_run_id` 及原镜像的两个配置摘要。

工作流分别核对文档与镜像来源、成功构建及已存在的版本内容，只更新仓库说明，再将 latest 指向已验证版本。它不构建或上传版本镜像。仓库简介按 UTF-8 保持在 100 字节内，完整说明保持在 25000 字节内；所有场景命令保留，不通过截断文本满足限制。
