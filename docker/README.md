# saga-server

独立 Saga 协调服务，提供动态流程定义、数据库持久恢复和多注册中心接入。Java、Go、Rust 业务可以保留各自的 Nacos 或 Consul，同一协调集群通过签名 HTTP 协议连接各环境的参与方，无需把业务服务迁入同一注册中心。

A standalone Saga orchestrator with workflow registration while the server stays running, durable recovery and multi-registry discovery. Already trusted business services add workflows without editing server YAML or restarting the coordinator, and can keep their own registry environments.

已接入的业务服务新增流程时，受管客户端主动上报签名定义、步骤能力及事务实例 ID，协调器保持运行，不需要修改服务端 YAML、热加载或重启。定义与实例保存在数据库中，YAML 管理基础设施、运行策略与信任范围。

- 镜像仓库：`nasaruntime/saga-server`，部署时选择明确版本或 digest。
- 平台：`linux/amd64`、`linux/arm64`；Alpine、musl，UID/GID `10001:10001`。
- 持久存储：MySQL 或 PostgreSQL，数据库需要预先创建。
- 许可证：MIT OR Apache-2.0。
- [源码与完整配置](https://github.com/nasa-runtime/saga-server)、[Dockerfile](https://github.com/nasa-runtime/saga-server/blob/release/1.0.0/docker/Dockerfile)。

## 运行架构与边界

协调状态、Inbox、Outbox、timer、流程目录和审计共用数据库。创建事务与首步命令持久化保持原子性；投递至少一次，参与方必须实现持久幂等和业务补偿。副本共享数据库，租约与 fencing 限制失权推进；副本身份必须唯一且重启稳定。

Nacos、Consul 只负责入口定位。具名 `qualifier` 不跨环境回退，业务入口与能力续租、结果回传的恢复入口分别管理。注册中心不复制 Saga 数据，不代替租户授权，也不保证参与方网络可达。协调器与参与方必须双向可达。

本镜像只装配 HTTP 协调角色，不执行业务步骤，不提供跨服务 ACID 或物理 exactly-once；gRPC、Kafka 和 Redis Streams 适配器未装配。Java、Go 参与方仍需实现完整的 Saga 协议，普通 REST 接口不能直接登记为步骤。

## 运行中接入新流程

流程拥有方发布包含 `workflow`、`definition_version` 和完整步骤合同的签名定义；各参与方登记可达能力并续租。动态 Catalog 持久化并同步这些事实，满足 `validated` 激活策略后，发起方携带 `saga_id` 和业务输入创建实例。定义名称与版本标识流程，`saga_id` 标识一次执行，服务端 YAML 不保存业务步骤清单或事务 ID。

业务服务可独立部署新流程、新步骤及新定义版本，既有实例继续使用冻结的定义版本和摘要。新流程须沿用已授权的身份、租户、公钥和网络范围；新增信任范围仍需调整部署配置。定义未激活时不能创建实例，`/readyz` 成功不能替代指定流程的状态检查。接入顺序与权限见[动态流程接入](https://github.com/nasa-runtime/saga-server/blob/release/1.0.0/docs/integration.md#流程动态上报与服务端持续运行)。

## 配置与启动

主配置位于 `/app/zcf/application.yml`，导入 `${SAGA_YML:/etc/saga-server/*.yml}`。文件按自然名称顺序合并，后者覆盖前者，列表整体替换。缺少导入文件、凭据或必填配置时拒绝启动。配置变更需要重启，动态流程定义和能力租约独立同步。

准备本地目录，将[授权模板](https://github.com/nasa-runtime/saga-server/blob/release/1.0.0/examples/config/10-security.yml)保存为 `deploy-local/config/10-security.yml`，按实际接入身份配置 caller、租户、参与方地址和凭据映射。Registry caller 必须声明允许的 workflow 范围。

模板为可信定义管理方使用 `workflows: ["*"]`，允许其在显式授权的租户内管理新增流程，不逐个预置名称。此范围不按流程名称隔离，流程归属检查仍生效，仅适用于可信流程拥有方；身份认证、签名校验和网络白名单继续生效。新增不受信身份、公钥或网络范围仍需维护信任配置，具体流程和步骤由业务侧动态发布。

```sh
mkdir -p deploy-local/config
```

创建 `deploy-local/saga.env`，以下值需要由部署方填写，文件不要提交到仓库：

```dotenv
SAGA_DATABASE_DRIVER=mysql
SAGA_DATABASE_URL=mysql://saga_user:URL_ENCODED_PASSWORD@mysql.internal:3306/saga_control
SAGA_REPLICA_ID=saga-server-0
SAGA_SERVICE_ID=saga-server
SAGA_LOG_PATH=
SAGA_COMMAND_KEY=REPLACE_WITH_64_LOWERCASE_HEX_CHARACTERS
SAGA_RESULT_KEY=REPLACE_WITH_ANOTHER_64_LOWERCASE_HEX_CHARACTERS
SAGA_PAGE_TOKEN_KEY=REPLACE_WITH_ANOTHER_64_LOWERCASE_HEX_CHARACTERS
SAGA_CLIENT_KEY=REPLACE_WITH_ANOTHER_64_LOWERCASE_HEX_CHARACTERS
SAGA_WORKER_KEY=REPLACE_WITH_ANOTHER_64_LOWERCASE_HEX_CHARACTERS
SAGA_DEFINITION_PUBLIC_KEY=REPLACE_WITH_BASE64_SPKI_ED25519_PUBLIC_KEY
```

每个 HMAC 密钥分别使用 `openssl rand -hex 32` 生成。定义公钥为 Base64 编码的 SPKI DER，流程拥有方保管对应 PKCS8 DER 私钥，协调器只接收公钥。生成方法、权限和协议见[业务接入](https://github.com/nasa-runtime/saga-server/blob/release/1.0.0/docs/integration.md)。切换 PostgreSQL 时使用 `SAGA_DATABASE_DRIVER=postgresql` 和 `postgres://...` URL。运行账号需要组件初始化所需的 DDL 权限及持久表读写权限。

```sh
chmod 600 deploy-local/saga.env
export SAGA_IMAGE=nasaruntime/saga-server:1.0.0
docker run --detach --name saga-server \
  --restart unless-stopped --stop-timeout 70 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
  --env-file ./deploy-local/saga.env \
  --mount "type=bind,src=$PWD/deploy-local/config,dst=/etc/saga-server,readonly" \
  --publish 127.0.0.1:2070:2070 \
  "$SAGA_IMAGE"
curl --fail http://127.0.0.1:2070/healthz
curl --fail http://127.0.0.1:2070/readyz
```

空日志路径只输出控制台；不设置时默认文件日志目录为 `/usr/local/logs/${application.name}`，必须挂载 UID 10001 可写目录。容器内 `localhost` 指向容器自身；数据库和参与方必须使用容器可达地址。上例只允许宿主机访问，跨主机部署需指定受控内网 IP 和防火墙。

## Nacos、Consul 与多注册中心

默认关闭注册发现，调用方可使用固定 HTTP URL。启用单套 Nacos 时，在同一环境文件中增加：

```dotenv
APP_PROFILE=nacos
NACOS_SERVER_ADDR=http://nacos.internal:8848/nacos/
NACOS_NAMESPACE=public
NACOS_GROUP=SAGA_GROUP
NACOS_USERNAME=YOUR_NACOS_USERNAME
NACOS_PASSWORD=YOUR_NACOS_PASSWORD
SAGA_REGISTER_IP=192.168.10.20
SAGA_REGISTER_PORT=12070
```

对应端口映射改为 `192.168.10.20:12070:2070`。Nacos 使用 Nacos 3 HTTP API，不需要 SDK gRPC 端口。默认发布 `saga-server` 和 `saga-server-recovery`；Saga 身份及映射端点 metadata 由框架生成，不能用手工同名注册代替。

`APP_PROFILE=multi-nacos` 向两套 Nacos 发布；`APP_PROFILE=consul` 使用固定 Consul agent 和 TTL 检查。Nacos/Consul 混合环境使用挂载配置。Kubernetes adapter 只读，部署方提供原生 Service 或受信代理入口。[完整多注册中心配置](https://github.com/nasa-runtime/saga-server/blob/release/1.0.0/docs/discovery.md)说明独立凭据、qualifier、映射端口和恢复通道。

## 调用、恢复与观测

业务方通过 `/_nasa/saga` 下的签名 HTTP API 发布定义、登记能力、创建和查询流程。HTTP 200 的 `Committed` 或 `Duplicate` 仅说明创建结果，业务终态另行查询。HTTP 签名覆盖实际 path 和原始 body，代理必须保留请求头、路径和正文。事务冲突或暂不可用可能返回 503；结果不明时保留相同业务身份与内容，使用新的时间戳、nonce 和签名进行有界退避重试。

`/healthz` 表示存活，`/readyz` 表示业务就绪。能力失效时普通入口可被撤出，恢复路径仍需允许受信续租和结果回传；恢复地址不会绕过鉴权或业务门禁。停机先撤销资格与注册，再排空资源，停止宽限期应大于 60 秒。

`9464/metrics` 提供 nafana 应用、Outbox 和发现指标，`2070/_nasa/saga/metrics` 提供持久 Saga 状态和生命周期分位数。只允许监控网络访问；多副本共享数据库指标按同一数据库去重，不能直接求和。当前阶段耗时直方图受预留容量限制，使用生命周期分位数并监控指标拒绝计数。[监控配置](https://github.com/nasa-runtime/saga-server/blob/release/1.0.0/docs/monitoring.md)包含 Prometheus、Grafana、告警和聚合语义。

业务通信、配置与监控部署的完整说明：[中文](https://github.com/nasa-runtime/saga-server/blob/release/1.0.0/README.md)、[English](https://github.com/nasa-runtime/saga-server/blob/release/1.0.0/README.en.md)。

## 源码构建与镜像发布

维护分支为 `master`，发布分支为 `release/<Cargo.toml 中的软件版本>`，例如 `release/1.0.0`。Build 工作流在对应发布分支生成 `linux/amd64` 和 `linux/arm64` 镜像归档，不自动上传镜像。构建分支必须与 manifest 版本一致，归档保留 3 天；过期后需要重新构建。

GitHub Actions 使用以下仓库配置：

| 类型 | 名称 | 用途 |
| --- | --- | --- |
| Variable | `DOCKERHUB_USERNAME` | 有目标仓库推送及更新仓库说明权限的账号 |
| Variable | `DOCKERHUB_NAMESPACE` | `nasaruntime`，与镜像名及文档一致 |
| Secret | `DOCKERHUB_TOKEN` | 上述账号的访问凭据，不写入源码、环境样例或日志 |

在对应发布分支手工运行 `Publish Docker image`，提供成功 Build 的 `build_run_id` 以及两个归档的 `amd64_config_digest`、`arm64_config_digest`。摘要采用 `sha256:` 格式，来自各归档实际配置文件。工作流核对 `master`、发布分支与构建提交相同，核对归档和装载后镜像身份，再上传这两个既有镜像。

发布先生成明确软件版本的多架构标签，例如 `nasaruntime/saga-server:1.0.0`，回读内容并更新仓库说明后，再使 `latest` 指向该版本。已有版本指向不同内容时拒绝覆盖，需要选择新的软件版本；镜像仓库无法读取或内容无法确认时停止。不会在发布阶段重建镜像替换已核对的归档。
