# saga-server

[English](README.en.md)

`saga-server` 是使用 NASA 组件构建的独立 Saga 协调服务。部署方运行容器并挂载配置，业务方注册流程定义、实现参与步骤并发起 Saga，无需为每个业务项目重新组装协调器或从 NASA 源码构建服务端。

入口使用 `#[nasa::application]`，由 napp 接管数据库、Saga、Outbox、HTTP、日志、多注册中心以及 nafana 指标出口。应用使用 crates.io 的 `nasa 2.0.5`，协调状态机、协议、幂等与恢复机制均由 NASA 组件提供。

协调服务持续运行期间，已接入的业务服务可主动发布新的流程定义和步骤能力，再提交事务实例 ID；新增流程不需要修改服务端 YAML、热加载或重启。服务端配置管理基础设施与信任范围，业务流程保存在动态目录中。

Java、Go 与 Rust 服务可以保留各自的注册中心，同一协调集群可同时服务多套 Nacos 或 Consul 环境，无需将业务服务迁入同一注册中心。NASA 客户端通过 `qualifier` 选择发现环境，各语言客户端也可使用固定 HTTP 地址。参与方以 Saga 能力协议发布可达步骤端点；业务入口与续租、结果回传的恢复入口分别管理，避免能力失效后无法恢复。语言互通仍要求实现相同的 Saga 协议，完整配置见[多注册中心部署](docs/discovery.md)。

## 能力与架构

```mermaid
flowchart LR
    Client[业务发起方] -->|签名 HTTP| Server[saga-server / napp]
    Owner[流程定义拥有方] -->|签名定义与能力注册| Server
    Server --> DB[(MySQL 或 PostgreSQL)]
    Server -->|持久 Outbox 命令| Worker[业务参与方]
    Worker -->|结果与能力续租| Server
    Prom[Prometheus] -->|指标抓取| Server
    Grafana[Grafana] --> Prom
    Server -.具名多目标注册.-> Nacos[Nacos / Consul]
```

- 同一镜像通过配置选择 MySQL 或 PostgreSQL；协调状态、Inbox、Outbox、timer、Catalog 与审计保存在数据库中。
- 动态 Definition Catalog：业务拥有方发布 Ed25519 签名的不可变流程定义，参与方注册并续租步骤能力。已授权范围内增加业务流程无需改动协调服务配置、重建镜像或重启。
- 持久 timer、至少一次投递、Inbox 幂等、显式补偿、结果裁决和人工处置。实例创建时冻结定义版本及摘要，运行中的流程不随新定义改变。
- HTTP HMAC 鉴权、共享数据库防重放、租户与流程范围授权、参与方地址白名单。
- 具名连接独立管理凭据、发现证据和注册目标；显式 qualifier 不跨环境回退。
- 多副本共享数据库；租约与 fencing 限制失权实例继续推进。副本身份必须唯一且重启稳定。
- nafana 输出运行指标，Prometheus 抓取并由 Grafana 展示流程状态、积压、端到端耗时和 Outbox 状态。

本镜像提供 HTTP 控制面与 HTTP command/result 数据面。NASA 的 gRPC、Kafka、Redis Streams 适配器未装配到此二进制。服务不执行业务步骤，不生成业务补偿，不提供跨服务 ACID 或物理 exactly-once，也不替业务处理多个 Saga 对同一资源的竞争。

## 运行中接入新流程

流程拥有方通过 `#[nasa::saga_workflow]` 声明完整定义，受管客户端签名并主动上报流程名、定义版本、步骤顺序及补偿、超时等合同。各参与方主动上报步骤能力及可达端点并续租；定义与能力符合 `validated` 策略后，协调器动态激活流程。业务请求随后携带 `saga_id` 创建具体事务实例，服务端不通过配置文件预置事务 ID 或业务步骤。

业务微服务可以独立部署新增流程，协调服务保持运行。`saga_id` 是一次执行的实例身份，`workflow` 与 `definition_version` 标识流程定义，两者不能混用。定义版本不可原地修改，已开始的实例继续使用冻结的定义；新定义不改变既有事务的执行步骤。完整接入见[业务接入](docs/integration.md#流程动态上报与服务端持续运行)。

前提是新流程沿用已授权的身份、租户、签名公钥和参与方网络范围。模板以 `workflows: ["*"]` 授予可信拥有方流程名称范围，定义归属检查仍生效；精确名称列表只允许列出的流程。未激活定义不能发起实例，`/readyz` 成功也不代表某个新流程已经可用。按[动态目录观测](docs/monitoring.md#动态目录与新流程接入)核对定义状态和能力续租，无需通过重启触发同步。

## 配置与凭据

以下命令在源码仓库根目录执行；只使用容器的部署方也可按 [Docker Hub 使用说明](docker/README.md)下载所需配置，不必安装 Rust。

```sh
git clone --branch release https://github.com/nasa-runtime/saga-server.git
cd saga-server
```

主配置位于镜像 `/app/zcf/application.yml`；默认导入 `${SAGA_YML:/etc/saga-server/*.yml}`。同一通配模式按文件名自然顺序合并，后面的文件覆盖前面文件，列表整体替换。没有匹配文件、无效配置或缺少必需凭据时拒绝启动。

```sh
mkdir -p deploy-local/config
cp examples/config/10-security.yml deploy-local/config/
```

编辑复制的文件，将示例 `system`、`order-api`、`order-worker` 和参与方地址替换为实际接入身份与网络范围。API caller 的 `credential_ref`、租户、权限需要显式声明；模板为可信流程拥有方配置 `workflows: ["*"]`，允许其在指定租户内发布和管理新增流程，无需逐个维护流程名。此范围不按流程名称隔离，仍受定义归属检查约束，只能授予可信定义管理方。`producer_credentials` 将每个结果生产方绑定到自己的凭据；引入新的身份、签名公钥或网络范围仍需维护部署信任配置。

在 `deploy-local/saga.env` 中填写以下变量；文件不要提交到仓库：

```dotenv
SAGA_DATABASE_DRIVER=mysql
SAGA_DATABASE_URL=mysql://saga_user:URL_ENCODED_PASSWORD@mysql.internal:3306/saga_control
SAGA_REPLICA_ID=saga-server-0
SAGA_SERVICE_ID=saga-server
SAGA_ENVIRONMENT=production
SAGA_CLUSTER=orders
SAGA_LOG_PATH=
SAGA_COMMAND_KEY=REPLACE_WITH_64_LOWERCASE_HEX_CHARACTERS
SAGA_RESULT_KEY=REPLACE_WITH_ANOTHER_64_LOWERCASE_HEX_CHARACTERS
SAGA_PAGE_TOKEN_KEY=REPLACE_WITH_ANOTHER_64_LOWERCASE_HEX_CHARACTERS
SAGA_CLIENT_KEY=REPLACE_WITH_ANOTHER_64_LOWERCASE_HEX_CHARACTERS
SAGA_WORKER_KEY=REPLACE_WITH_ANOTHER_64_LOWERCASE_HEX_CHARACTERS
SAGA_DEFINITION_PUBLIC_KEY=REPLACE_WITH_BASE64_SPKI_ED25519_PUBLIC_KEY
```

每个 HMAC 密钥使用独立的 `openssl rand -hex 32` 输出。分页密钥至少 32 字节；示例使用 64 字符随机十六进制文本。所有协调副本使用相同的信任配置和分页密钥。公钥格式是 **Base64(SPKI DER)**，不是 PEM 文本，也不是裸 32 字节公钥；流程发布者持有对应的 **Base64(PKCS8 DER)** 私钥。可使用 `ncrypto::generate_ed25519_key_pair()` 生成，或使用 OpenSSL：

```sh
umask 077
openssl genpkey -algorithm ED25519 -out deploy-local/definition-private.pem
openssl pkey -in deploy-local/definition-private.pem -pubout -outform DER -out deploy-local/definition-public.der
openssl base64 -A -in deploy-local/definition-public.der
chmod 600 deploy-local/saga.env
```

将 `openssl base64` 输出的公钥写入 `SAGA_DEFINITION_PUBLIC_KEY`。私钥只交给流程拥有方，不能挂载给协调服务。密钥用途、API 和业务接入见 [业务接入指南](docs/integration.md)。

数据库必须预先创建。服务账号需要读取与修改 Saga 持久表的权限，启动时还需要组件建表和校验结构所需的 DDL 权限；不使用数据库管理员账号作为长期运行账号。协调数据源必须与其 Inbox、Outbox、Catalog 保持一致。

切换 PostgreSQL 只需修改：

```dotenv
SAGA_DATABASE_DRIVER=postgresql
SAGA_DATABASE_URL=postgres://saga_user:URL_ENCODED_PASSWORD@postgres.internal:5432/saga_control
```

配置在启动时加载。修改本地 YAML、环境、凭据、数据库或网络配置后需重启进程；业务流程定义与参与方能力由动态 Catalog 持续同步，独立于本地配置加载。

## Docker 启动

`SAGA_IMAGE` 指向完整标签或 digest；以下使用 `nasaruntime/saga-server:1.0.0`。镜像采用 Alpine、UID/GID `10001:10001`。上述环境文件将 `SAGA_LOG_PATH` 显式设为空，只输出控制台日志，可使用只读根文件系统；未设置该变量时，默认文件日志目录为 `/usr/local/logs/${application.name}`，需要挂载 UID 10001 可写目录。挂载配置须允许 UID 10001 读取，密钥只从环境文件注入。

```sh
export SAGA_IMAGE=nasaruntime/saga-server:1.0.0
docker pull "$SAGA_IMAGE"
docker run -d --name saga-server \
  --restart unless-stopped \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --stop-timeout 70 \
  --env-file ./deploy-local/saga.env \
  --mount type=bind,src="$(pwd)/deploy-local/config",dst=/etc/saga-server,readonly \
  --publish 127.0.0.1:2070:2070 \
  "$SAGA_IMAGE"
curl --fail http://127.0.0.1:2070/healthz
curl --fail http://127.0.0.1:2070/readyz
```

不使用注册中心时保持默认配置即可。业务方使用 `http://宿主机可达地址:映射端口/_nasa/saga`；同一 Docker 网络内可以使用 `http://saga-server:2070/_nasa/saga`。上面绑定 `127.0.0.1` 只允许宿主机访问，跨主机访问应改为具体内网 IP 并配置防火墙。容器中的 `localhost` 是容器自身；数据库和参与方地址必须从容器网络可达。

| 参数 | 作用 |
| --- | --- |
| `SAGA_YML` | 导入文件或通配模式；默认 `/etc/saga-server/*.yml` |
| `SAGA_DATABASE_DRIVER` | `mysql`（默认）或 `postgresql` |
| `SAGA_DATABASE_URL` | 必填，已有数据库的连接 URL，密码中的特殊字符需 URL 编码 |
| `SAGA_REPLICA_ID` | 必填，同一协调服务中唯一、重启稳定的副本身份 |
| `SAGA_SERVICE_ID` | 逻辑服务身份，默认 `saga-server`，同一服务的副本保持一致 |
| `SAGA_ENVIRONMENT` / `SAGA_CLUSTER` | 指标环境和集群标签，默认均为 `local` |
| `SAGA_METRICS_INSTANCE_ID` | 指标实例身份，默认引用 `saga.replica_identity` |
| `SAGA_LOG_LEVEL` / `SAGA_LOG_PATH` | 默认 `info` / `/usr/local/logs/${application.name}`；显式空路径只输出控制台，非空路径需 UID 10001 可写目录 |
| `APP__SERVER__PORT` | 改变实际监听端口，默认 `2070`；修改时同步容器探针和 Prometheus 目标 |
| `SAGA_REGISTER_PORT` / `SECONDARY_REGISTER_PORT` | 内置 profile 向各环境发布的可达端口，默认 `2070`；端口映射时显式指定宿主机端口 |

Docker 内置健康检查访问 `2070/readyz`。`/healthz` 表示进程存活，`/readyz` 表示可接收业务，两者不能互相替代。启动和停机预算均为 60 秒，容器停止宽限期应更长。监控端口 `9464` 只供受信网络抓取，不应直接暴露到公网。

### Docker Compose 部署

也可使用仓库中的 [Compose 配置](docker/compose.yml)，它复用同一环境文件和授权目录，连接已有数据库。以下与上面的 `docker run` 二选一，不要同时占用宿主机 2070 端口：

```sh
docker compose -p saga -f docker/compose.yml pull
docker compose -p saga -f docker/compose.yml up -d
docker compose -p saga -f docker/compose.yml ps
docker compose -p saga -f docker/compose.yml logs --tail 100 saga-server
curl --fail http://127.0.0.1:2070/readyz
```

仅在计划维护或升级时执行 `docker compose -p saga -f docker/compose.yml stop`。再次启动使用原数据库、原副本身份与信任配置；不要为了新增业务流程执行停机。需要同时运行监控时直接使用下方监控 Compose，它已经包含协调服务。

## 发起和查询一个 Saga

先接入一个流程拥有方和步骤参与方，按[业务接入指南](docs/integration.md#参与方与流程拥有方)完成本地持久存储、签名定义发布和能力续租。协调镜像没有内置 `order_checkout` 或业务步骤；下面假设业务方已发布该流程的定义版本 `1`，首步骤接受 `order_id` 与 `quantity`。业务方新增流程通过相同协议上报，服务端保持运行。

[HTTP 示例程序](examples/saga-http.py)只依赖 Python 3 标准库，支持查询定义、创建实例和查询状态。`SAGA_HTTP_KEY` 填对应 caller 的密钥，不能混用 worker 和 API caller 的密钥；交互输入时不回显。

```sh
export SAGA_BASE_URL=http://127.0.0.1:2070/_nasa/saga
export SAGA_HTTP_PRODUCER=order-worker
read -r -s SAGA_HTTP_KEY
export SAGA_HTTP_KEY
python3 examples/saga-http.py definition \
  --tenant system --workflow order_checkout --definition-version 1
```

以上输入 `SAGA_WORKER_KEY` 的值，确认定义已激活后再发起。切换为 `order-api`，再次输入 `SAGA_CLIENT_KEY` 的值，并准备与流程合同一致的输入：

```sh
export SAGA_HTTP_PRODUCER=order-api
read -r -s SAGA_HTTP_KEY
export SAGA_HTTP_KEY
cat > deploy-local/order.json <<'JSON'
{"order_id":"order-1001","quantity":1}
JSON
python3 examples/saga-http.py start \
  --tenant system --workflow order_checkout --definition-version 1 \
  --saga-id order-1001 --business-key order-1001 --trigger-id checkout-1001 \
  --input-file deploy-local/order.json
python3 examples/saga-http.py get --tenant system --saga-id order-1001
unset SAGA_HTTP_KEY
```

创建返回 HTTP 200 的 `Committed` 或 `Duplicate` 只表示创建事实已持久化，最终状态由查询确认。结果不明时保留原实例 ID、业务键、触发 ID 和输入，再次执行同一命令会生成新的 nonce 和签名；不要换成新事务 ID。示例不自动重试、不跟随 HTTP 重定向，失败保留原 HTTP 状态，详细权限和失败处理见[接口合同](docs/integration.md#接口与失败语义)。

## 使用 Nacos

在同一份环境文件中增加：

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

将端口映射改为 `--publish 192.168.10.20:12070:2070`。发布地址必须是调用方可达的 IP 和端口，
不能填写 `0.0.0.0`；新配置不隐式读取 `LOCAL_NETWORK_IP`。Nacos 采用 Nacos 3 HTTP API，
此模式不需要 SDK gRPC 端口。配置中心仍使用本地挂载文件。

profile 会发布 `saga-server` 与 `saga-server-recovery` 两个服务，分别承接普通业务发现和恢复
发现。名称随 `SAGA_SERVICE_ID` 改变；Saga metadata 由框架按实际映射端点生成。

## 多注册中心与共享协调集群

协调集群以共享数据库中的 Saga、Inbox、Outbox、timer 和 Catalog 为持久事实，注册中心不承担
任务选主或状态复制。`APP_PROFILE=multi-nacos` 将同一副本发布到 `primary`、`secondary` 两套
环境，配置见[多注册中心部署](docs/discovery.md)。`APP_PROFILE=consul` 使用 Consul 固定 agent
和独立 TTL 检查；自定义挂载配置可以同时组合不同后端。

双 Nacos 在上面单套配置的基础上，将 `APP_PROFILE` 改为 `multi-nacos`，再增加第二套完整变量：

```dotenv
APP_PROFILE=multi-nacos
SECONDARY_NACOS_SERVER_ADDR=http://nacos-secondary.internal:8848/nacos/
SECONDARY_NACOS_NAMESPACE=public
SECONDARY_NACOS_GROUP=SAGA_GROUP
SECONDARY_NACOS_USERNAME=YOUR_SECONDARY_NACOS_USERNAME
SECONDARY_NACOS_PASSWORD=YOUR_SECONDARY_NACOS_PASSWORD
SECONDARY_REGISTER_IP=192.168.20.20
SECONDARY_REGISTER_PORT=22070
```

两个网络入口分别发布 `192.168.10.20:12070:2070` 和 `192.168.20.20:22070:2070`，转发至同一个容器的 2070 端口；IP 必须属于宿主机或由受信网关提供。两个环境各自发现自己的可达地址，共享同一套 Saga 数据。Consul 单后端在同一环境文件选择以下配置，替换原 `APP_PROFILE`：

```dotenv
APP_PROFILE=consul
CONSUL_API_ADDR=http://consul.internal:8500
CONSUL_AGENT_ADDR=http://consul-agent.internal:8500
CONSUL_DATACENTER=dc1
CONSUL_TOKEN=YOUR_CONSUL_TOKEN
SAGA_REGISTER_IP=192.168.10.20
SAGA_REGISTER_PORT=12070
```

```mermaid
flowchart LR
    Java[Java 业务] -.查询业务或恢复入口.-> Nacos[Nacos 环境]
    Go[Go 业务] -.查询业务或恢复入口.-> Consul[Consul 环境]
    Server[saga-server 协调副本] -.primary 注册.-> Nacos
    Server -.consul-go 注册.-> Consul
    Java -->|签名 HTTP| Server
    Go -->|签名 HTTP| Server
    Server --> DB[(共享协调数据库)]
    Server -->|按能力路由投递命令| Workers[可达的参与方端点]
    Workers -->|续租与结果回传| Server
```

注册中心只提供入口定位。请求进入协调器后使用同一组持久事实、定义和授权；向多个注册中心
发布不会创建多份 Saga，也不会复制数据库。协调器向参与方投递命令时使用能力登记的端点，
不把参与方服务名拿到其它注册中心重新匹配。每套环境必须具备到协调入口的网络路径，协调器
也必须能访问参与方端点。

可直接导入 [Nacos 与 Consul 混合配置](examples/config/discovery-mixed.yml)，按
[混合部署步骤](docs/discovery.md#consul-与混合后端)填写环境变量。`primary`、`consul-go` 是连接名；
`coordinator`、`recovery` 是连接内的服务别名；`SAGA_SERVICE_ID` 是协议验证的逻辑协调身份。
调用方的连接名称可以不同，但必须指向正确的后端范围并信任同一协调身份。

| 业务环境 | 接入方式 | 配置要求与边界 |
| --- | --- | --- |
| 多套 Nacos，或不同 namespace/group | 多目标注册与具名发现 | 每个连接独立配置范围和凭据；注册目标显式选择 qualifier |
| Nacos 与 Consul 混合 | 同一副本向不同后端发布 | 服务别名、可达端点和健康策略分别配置，失败不跨环境回退 |
| Kubernetes | 原生 Service 或受信代理入口 | adapter 只读；Saga 可使用完整 Service DNS URL，原生端点不自动带 Saga 身份 metadata |
| 无注册中心或暂不升级客户端 | 固定 URL / HTTP 负载均衡 | 默认 `discovery.enabled: false`，协调与恢复照常运行 |
| 数据与信任域需要完全隔离 | 独立协调集群与数据库 | 多注册中心不合并数据库，不代替租户授权或网络隔离 |

### 业务应用选择协调环境

Rust 业务应用使用 `discovery` 组件，把自己的注册目标留在 `primary`，另建 `saga-infra` 连接。
`saga.discovery.<名称>.qualifier: saga-infra` 选择该连接，`service` 选择连接内服务别名。
完整的双目标客户端配置见[qualifier 与业务方接入](docs/discovery.md#qualifier-与业务方接入)。

发起新 Saga 使用普通 `coordinator` 服务，参与方的能力登记、定义同步与结果回传使用 `recovery`
服务；身份校验和地址白名单都必须保留。不能只在注册中心手工添加同名 IP/端口来代替框架注册。

### Java、Go、Rust 使用独立 Nacos

需要固定 URL 接入时，可以采用一个受信的协调集群入口，例如 `https://saga.internal/_nasa/saga`。Java、Go、Rust 的服务注册、配置中心和内部调用继续使用各自原有的 Nacos，Saga 通信通过可达的 HTTP 地址完成。

```mermaid
flowchart LR
    Java[Java 服务] -.注册发现.-> NJ[Java Nacos]
    Go[Go 服务] -.注册发现.-> NG[Go Nacos]
    Rust[Rust 服务] -.注册发现.-> NR[Rust Nacos]
    Java -->|签名 HTTP| Entry[saga.internal]
    Go -->|签名 HTTP| Entry
    Rust -->|签名 HTTP| Entry
    Entry --> A[saga-server-0]
    Entry --> B[saga-server-1]
    A --> DB[(共享协调数据库)]
    B --> DB
    A -->|按能力路由发送命令| Workers[各环境参与方端点]
    B -->|按能力路由发送命令| Workers
```

1. 部署共享数据库的协调副本，在前面设置内网负载均衡入口。协调端可保持 Nacos 关闭；也可注册到自己的基础设施 Nacos，业务使用 URL 时不必访问这套 Nacos。
2. 业务发起方将 Saga 基础地址设为 `https://saga.internal/_nasa/saga`，按 HTTP 接口合同发起和查询流程。Rust 受管 client 设置 `saga.client.orchestrator_discovery_ref` 为该完整 URL。
3. 参与方将能力注册、定义发布和结果回传都指向这个协调入口。以下是 Rust 参与方在完整接入配置上合并的覆盖片段，不是完整应用配置：

```yaml
saga:
  definition_catalog:
    registry_client:
      discovery_ref: https://saga.internal/_nasa/saga
  transport:
    command_result:
      http:
        orchestrator_discovery_ref: https://saga.internal/_nasa/saga
        advertised_endpoint: https://rust-order-0.internal
```

`advertised_endpoint` 是协调器能够访问的参与方 origin，不包含 `/_nasa/saga`；实际 Saga 路由前缀随能力描述一并登记。每个副本使用自己的 `replica_identity` 和准确端点，命令必须到达所选能力对应的参与实例或明确共享相同持久幂等与能力合同的后端，不能任意转发到不匹配的副本。TLS 可以由受信代理终止，代理需保持实际 Saga 路径。

协调器按参与方提交并续租的能力端点发命令，无需订阅 Java、Go、Rust 的 Nacos。协调器与参与方之间必须双向可达：业务能访问协调入口，协调器也能访问参与端点；Nacos 可达并不能替代这些网络条件。

在协调端导入配置中，将 `saga-participants` 地址白名单调整为实际端点，例如：

```yaml
saga:
  transport:
    address_policies:
      saga-participants:
        http_schemes: [https]
        http_hosts: [java-order-0.internal, go-stock-0.internal, rust-order-0.internal]
        http_ports: [443]
```

该片段会整体替换同名策略里的列表，必须列出全部需要保留的主机与端口。白名单只允许网络目标；每个参与方还需在 [授权配置](examples/config/10-security.yml) 中声明独立 secret、`producer_credentials` 结果身份，以及具有正确 tenant/workflow 范围的 Registry caller。流程拥有方另外配置定义签名公钥映射，协调服务只接收公钥。

### Java 与 Go 的协议接入要求

| 业务职责 | 需要实现的合同 |
| --- | --- |
| 只发起和查询 Saga | 按 [HTTP 接口说明](docs/integration.md) 发送 JSON、计算 HMAC、设置调用身份，保留业务幂等标识并处理原生 HTTP 状态 |
| 发布流程定义 | 生成符合 NASA 合同的规范化 DefinitionArtifact、摘要及 Ed25519 签名，通过授权 Registry 发布 |
| 执行业务步骤 | 注册并续租能力，接收并验证 command，持久化 Inbox 与业务效果，支持该步骤声明的取消、裁决及补偿语义，以 Outbox 或等价持久机制回传 result |

本项目提供 Rust NASA 组件接入示例，不随附 Java 或 Go 参与端 SDK。Java/Go HTTP 客户端可以实现发起与查询；完整参与端需要协议适配层，不能仅把已有业务 REST 地址登记为 Saga 步骤。Nacos 注册本身不提供 Saga 的幂等、补偿和能力合同。

同一流程可以在协议适配完成后调用不同语言实现的步骤。各步骤 owner 在工作流中明确声明；即使不同 Nacos 中存在同名服务，也不能将其视为同一 Saga 身份。所有调用身份、租户、流程授权和密钥必须在协调侧明确配置；Nacos namespace 不自动映射为 Saga tenant。

### 协调副本与负载均衡

所有协调副本使用相同的 `SAGA_DATABASE_URL`、`SAGA_SERVICE_ID`、授权配置、信任材料和分页密钥；副本分别设置 `SAGA_REPLICA_ID=saga-server-0`、`saga-server-1` 等，身份唯一且重启稳定。每个副本挂载部署配置；当前本地配置变更需要逐副本重启。数据库需要独立的高可用部署，负载均衡入口也应避免单点。

负载均衡需要区分以下通道，不能只配置一条以 `/readyz` 决定所有请求去留的规则：

| 通道 | 路由要求 |
| --- | --- |
| 新 Saga 与普通业务操作 | 向 `/readyz` 通过的协调副本转发，未就绪时停止接收新工作 |
| `POST /_nasa/saga/registry/capabilities` | 保留到具备恢复资格副本的路径，允许启动后和能力租约失效时重新登记；由组件继续执行认证与能力校验 |
| `POST /_nasa/saga/results` | 保留到具备恢复资格副本的路径，由组件判定 Catalog、定义与生产方信任是否仍允许结果收敛 |

启用内置 discovery profile 时，恢复后端池使用 `/discovery/eligible/primary-recovery` 判断本地
恢复资格，普通业务池使用 `/readyz`。资格探针不查询注册中心，也不证明注册记录当前可用；
远端发布状态另由 `napp_discovery_registration_ready` 反映。`/healthz` 仅检查存活，不能代替
恢复资格。未启用 discovery 的固定 URL 部署没有该资格探针，应保留独立恢复路径，结合
存活检查和平台停机摘流；每个请求仍由 Saga 复验生命周期、认证与事务门禁。

若所有副本因缺少能力路由而未就绪，阻断全部 Registry 请求会使参与方无法续租，集群也就无法
恢复就绪。恢复地址与普通地址可以指向同一个 HTTP listener，路由隔离不授予额外权限；即使
通过恢复地址发送新 Saga，也不会绕过业务就绪门禁。停机时先撤销资格与注册，再排空并关闭连接。

HTTP 签名覆盖实际 path 与原始 body。代理需透传 `x-saga-*` 请求头，不改写 Saga 路径或重新编码 JSON，不盲目自动重试 POST。调用方在结果不明时保留原业务身份与内容，使用新的时间戳、nonce 和签名重试；普通代理原样重放请求会触发防重放拒绝。各节点需保持时钟同步，符合 30 秒签名时效窗口。HTTPS 证书必须被调用方信任。

副本故障后的已领取任务可能等待租约到期后接管。默认 timer 租约为 60 秒，`timer_poll_interval_ms: 500` 不是故障恢复时间承诺。Prometheus 分别抓取各副本，共享数据库的数量指标按[监控指南](docs/monitoring.md)去重。

### 多注册中心的能力边界

连接和发布目标在启动时冻结，修改配置需要重启。默认 qualifier 为小写 `primary`，显式未知
名称立即拒绝；所选环境没有合法实例时，不切换到另一个同名服务。注册、健康、故障和清理均按
目标隔离；`startup_required` 与 `readiness_critical` 分别控制首次确认和运行期整体就绪影响。

注册中心可达不等于参与方可达。跨网络仍需受信路由或网关，协调器与参与方要双向可达。完全隔离
的业务环境应分别部署协调数据库和入口。Kubernetes 不支持应用自行写入注册记录，详见
[后端与恢复通道边界](docs/discovery.md)。

## Grafana 与 Prometheus

服务通过 NASA 的 `grafana` feature 使用 **nafana**，napp 自动托管 exporter，无需自行实现 metrics Router。随项目提供 Prometheus 双出口抓取、告警规则、Grafana 数据源与仪表盘。

准备好 `deploy-local/config` 与 `deploy-local/saga.env`，设置 Grafana 管理密码后启动：

此部署已包含协调服务，与单独的 `docker run` 或基础 Compose 二选一；首次部署时选择所需方式，避免端口冲突及相同副本身份同时运行。

```sh
export GRAFANA_ADMIN_PASSWORD='REPLACE_WITH_A_STRONG_PASSWORD'
docker compose -p saga-monitoring -f docker/monitoring/compose.yml up -d
```

访问 Grafana `http://127.0.0.1:3000`，默认管理员名 `admin`，密码为上面的值；仪表盘位于 `Saga / Saga Server`。Prometheus 位于 `http://127.0.0.1:9090`。Compose 不创建业务数据库，数据库和参与方仍需在这个网络中可达。生产环境需要同步修改 Prometheus 配置中的环境、集群标签。

完整指标、抓取安全、多副本聚合和现有监控平台接入见 [监控指南](docs/monitoring.md)。

常用排查入口：`docker logs --tail 100 saga-server` 查看单容器日志；Compose 部署使用相应项目的 `logs` 命令。存活失败先查配置与数据库；已存活但未就绪时检查目录状态、能力续租和必要依赖；业务已就绪但新流程被拒绝时核对该定义是否激活、caller 权限与参与方合同。401 检查密钥和时钟，403 检查租户及流程授权，409 需要区分 HTTP 重放与业务身份冲突，503 不证明事务未提交。

`nasaga_stage_duration_seconds` 输出五个固定阶段的进程内直方图，共 85 条序列，进程重启后重新累计。仪表盘使用数据库中的持久生命周期分位数，两者统计范围不同；`nametrics_samples_rejected_total` 非零时需检查指标容量，抓取成功不能替代业务就绪或流程状态检查。

## 构建与运行边界

源码和镜像构建使用 crates.io 的 `nasa 2.0.5`，由 `Cargo.lock` 固定完整依赖图。使用 Rust 1.94 或更高版本构建：

```sh
cargo build --locked --release
bash docker/build-image.sh
```

Dockerfile、构建与发布脚本、Compose 部署文件均位于 `docker/`；GitHub Actions 工作流位于 `.github/workflows/`。Docker Hub 使用说明见 [镜像说明](docker/README.md)。

镜像脚本以服务目录作为构建上下文，`SAGA_IMAGE` 可覆盖输出标签。构建环境须能下载锁文件中的 registry 依赖，或预先准备对应的 Cargo 缓存。

此项目分发独立服务镜像，manifest 设置 `publish = false`。源码部署应保留 `Cargo.lock`，确保本地构建与镜像构建使用相同的组件版本。

Dockerfile 使用 Docker Hub 官方 `rust:1.94-alpine` 和 `alpine:3.23`，digest 固定对应内容。最终镜像只保留程序、默认配置、CA 证书和许可证，不包含 Rust 工具链、业务凭据或数据库数据。

支持按 `linux/amd64`（x86-64/x64）与 `linux/arm64` 构建；多架构构建需要支持相应架构的 builder。固定镜像标签或 digest，数据库备份、兼容性检查、灰度与回退由部署方管理。停止容器不会删除数据库中的 Saga 事实，恢复时使用相同数据库、逻辑身份和信任配置。

许可证：MIT OR Apache-2.0，见 [MIT](LICENSE-MIT) 和 [Apache-2.0](LICENSE-APACHE)。
