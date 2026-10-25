# saga-server

独立 Saga 协调服务，支持动态流程、持久恢复和多注册中心。新增已授权流程由客户端主动上报，协调器无需改 YAML 或重启。

- 镜像：`nasaruntime/saga-server:1.0.0`，支持 `linux/amd64`、`linux/arm64`。
- Alpine/musl，UID/GID `10001:10001`；持久存储使用已有 MySQL 或 PostgreSQL。
- MIT OR Apache-2.0；[源码与完整说明](https://github.com/nasa-runtime/saga-server)。

## 运行架构与边界

协调状态、Inbox、Outbox、timer、Catalog 与审计共用数据库。创建与首步命令原子提交；参与方实现持久幂等及补偿，租约与 fencing 限制失权推进。

Nacos/Consul 负责定位，不复制 Saga 数据或提供租户授权；具名 `qualifier` 不跨环境回退。协调器与参与方必须双向可达。本镜像只装配 HTTP 协调角色，不执行业务步骤，不提供跨服务 ACID 或物理 exactly-once；未装配 gRPC、Kafka、Redis Streams。

## 运行中接入新流程

流程拥有方发布含 `workflow`、`definition_version` 和步骤合同的签名定义，参与方登记能力并续租；满足 `validated` 策略后，发起方携带 `saga_id` 创建实例。既有实例使用冻结的定义版本与摘要。YAML 只管理基础设施、运行策略与信任范围。

新增信任范围仍需维护配置；定义激活后才能创建实例，Ready 不代表流程已激活。[业务接入协议](https://github.com/nasa-runtime/saga-server/blob/release/docs/integration.md)。

## 配置与启动

使用 Docker Compose 2.30.0 或更新版本，在同一部署目录准备三个文件：

```text
saga-server/
├── compose.yml       # 容器启动配置
├── application.yml   # 调用身份、租户、权限和参与方地址
└── .env              # 数据库连接、密钥和可选注册中心参数
```

### 1. 下载文件

在新目录执行，已有部署不要覆盖原配置：

```sh
mkdir saga-server
cd saga-server
curl --fail --location https://raw.githubusercontent.com/nasa-runtime/saga-server/release/docker/compose.yml --output compose.yml
curl --fail --location https://raw.githubusercontent.com/nasa-runtime/saga-server/release/examples/config/10-security.yml --output application.yml
curl --fail --location https://raw.githubusercontent.com/nasa-runtime/saga-server/release/docker/env.example --output .env
chmod 600 .env
chmod 644 application.yml
```

### 2. 填写配置

编辑 `.env`，填入已有数据库、稳定的副本身份、五个独立 HMAC 密钥及定义签名公钥。模板默认 MySQL；使用 PostgreSQL 只替换 `SAGA_DATABASE_DRIVER=postgresql` 和对应连接 URL。首次使用 MySQL 先完成[触发器初始化](#mysql-首次初始化与触发器权限)。数据库密码中的特殊字符须 URL 编码。

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

每个 HMAC 密钥分别用 `openssl rand -hex 32` 生成。定义公钥使用 Base64 SPKI DER；以下最后一条输出填入 `SAGA_DEFINITION_PUBLIC_KEY`，私钥只由流程拥有方保管：

```sh
umask 077
openssl genpkey -algorithm ED25519 -out definition-private.pem
openssl pkey -in definition-private.pem -pubout -outform DER -out definition-public.der
openssl base64 -A -in definition-public.der
```

需要 PKCS8 DER 私钥时执行 `openssl pkcs8 -topk8 -nocrypt -in definition-private.pem -outform DER -out definition-private.der`，再用 `openssl base64 -A -in definition-private.der` 编码，仅交给流程拥有方。

编辑 `application.yml`，将示例 `system`、`order-api`、`order-worker` 和参与方地址换成实际值。`workflows: ["*"]` 仅授予可信流程拥有方，定义归属、签名和网络白名单仍生效。没有这些业务身份与密钥时，服务不能安全接入参与方。

`.env` 每行使用 `KEY=value`，不加包裹引号或行尾注释。Compose 使用 `env_file` 的 `raw` 格式原样注入值，只挂载 `application.yml`。不要挂载整个部署目录，以免把 `compose.yml` 当业务配置读取。服务也可直接接收平台注入的环境变量，不强制使用 `.env` 文件。[环境文件规则](https://docs.docker.com/reference/compose-file/services/#env_file)。

### 3. 启动

```sh
docker compose up -d
docker compose logs --tail 100 saga-server
curl --fail http://127.0.0.1:2070/readyz
```

默认固定 HTTP 寻址，不需要 Nacos。容器内 `localhost` 指向自身，数据库和参与方使用容器可达地址。端口默认仅绑定 `127.0.0.1`，跨主机调用时在 `compose.yml` 修改为受控内网 IP。

`SAGA_LOG_PATH=` 表示控制台日志；配置文件需允许 UID 10001 读取。主配置导入 `${SAGA_YML:/etc/saga-server/*.yml}`，本方案只挂载一份业务文件；缺少必填配置时拒绝启动。基础设施与信任配置变更需计划重启，新增已授权业务流程无需修改这些文件。

### 使用 docker run

与 Compose 二选一，复用同目录的 `.env`、`application.yml`。下方其它场景命令也从此部署目录执行，先设置镜像变量：

```sh
export SAGA_IMAGE=nasaruntime/saga-server:1.0.0
docker pull "$SAGA_IMAGE"
docker run --detach --name saga-server \
  --restart unless-stopped --stop-timeout 70 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
  --env-file ./.env \
  --mount "type=bind,src=$PWD/application.yml,dst=/etc/saga-server/application.yml,readonly" \
  --publish 127.0.0.1:2070:2070 \
  "$SAGA_IMAGE"
curl --fail http://127.0.0.1:2070/readyz
```

### 配置与文件日志挂载

主 README 的简短命令保留只读 YAML 和可写日志目录。下面的完整形式同时限制根文件系统与 Docker 控制台日志。在 Linux 上创建本部署专用日志目录，Docker Desktop 需允许目录共享：

```sh
sudo install -d -o 10001 -g 10001 -m 0750 logs
docker run -d --name saga-server \
  --restart unless-stopped --stop-timeout 70 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
  --env-file ./.env --env SAGA_LOG_PATH=/usr/local/logs/saga-server \
  --mount "type=bind,src=$PWD/application.yml,dst=/etc/saga-server/application.yml,readonly" \
  --mount "type=bind,src=$PWD/logs,dst=/usr/local/logs/saga-server" \
  --publish 127.0.0.1:2070:2070 \
  nasaruntime/saga-server:1.0.0
curl --fail http://127.0.0.1:2070/readyz
```

此命令覆盖 `.env` 的空日志路径，与控制台模式择一；复用原数据库、密钥和副本身份。

## Nacos、Consul 与多注册中心

继续使用 Compose 时，填写下列 `.env` 参数，并在 `compose.yml` 的 `ports` 中设置对应映射，再执行 `docker compose up -d`。单套示例映射为 `192.168.10.20:12070:2070`，双套再增加 `192.168.20.20:22070:2070`；发布地址必须能从调用方到达。下方同时给出完整 `docker run` 命令，两种方式择一。

默认关闭 discovery。使用单 Nacos 时，在同一个 `.env` 中增加以下变量，每个变量只保留一行：

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

```sh
docker run --detach --name saga-nacos \
  --restart unless-stopped --stop-timeout 70 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
  --env-file ./.env \
  --mount "type=bind,src=$PWD/application.yml,dst=/etc/saga-server/application.yml,readonly" \
  --publish 192.168.10.20:12070:2070 \
  "$SAGA_IMAGE"
docker logs --tail 100 saga-nacos
curl --fail http://192.168.10.20:12070/readyz
curl --fail http://192.168.10.20:12070/discovery/eligible/primary-recovery
```

使用 Nacos 3 HTTP API，无需 SDK gRPC 端口。默认发布 `saga-server` 与 `saga-server-recovery`，Saga 身份和映射 metadata 由框架生成，不能用手工同名记录代替。

双 Nacos 在同一个 `.env` 中把 `APP_PROFILE` 改成 `multi-nacos`，保留第一套 Nacos 变量，再增加第二套：

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

```sh
docker run --detach --name saga-multi-nacos \
  --restart unless-stopped --stop-timeout 70 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
  --env-file ./.env \
  --mount "type=bind,src=$PWD/application.yml,dst=/etc/saga-server/application.yml,readonly" \
  --publish 192.168.10.20:12070:2070 \
  --publish 192.168.20.20:22070:2070 \
  "$SAGA_IMAGE"
docker logs --tail 100 saga-multi-nacos
curl --fail http://192.168.10.20:12070/readyz
curl --fail http://192.168.10.20:12070/discovery/eligible/primary-recovery
curl --fail http://192.168.20.20:22070/discovery/eligible/secondary-recovery
```

两条映射进入同一容器 listener，连接名分别为 `primary`、`secondary`，共享数据库事实。映射 IP 必须属于宿主机或由受信网关提供。相同 Nacos 地址的不同 namespace/group 也使用此模式，目标不能覆盖同一记录。

单 Consul 在同一个 `.env` 中替换 `APP_PROFILE` 并填写以下变量；agent 地址固定到管理本副本记录的 agent：

```dotenv
APP_PROFILE=consul
CONSUL_API_ADDR=http://consul.internal:8500
CONSUL_AGENT_ADDR=http://consul-agent.internal:8500
CONSUL_DATACENTER=dc1
CONSUL_TOKEN=YOUR_CONSUL_TOKEN
SAGA_REGISTER_IP=192.168.10.20
SAGA_REGISTER_PORT=12070
```

```sh
docker run --detach --name saga-consul \
  --restart unless-stopped --stop-timeout 70 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
  --env-file ./.env \
  --mount "type=bind,src=$PWD/application.yml,dst=/etc/saga-server/application.yml,readonly" \
  --publish 192.168.10.20:12070:2070 \
  "$SAGA_IMAGE"
docker logs --tail 100 saga-consul
curl --fail http://192.168.10.20:12070/readyz
curl --fail http://192.168.10.20:12070/discovery/eligible/primary-recovery
```

混合模式见下方命令。Rust 客户端可用额外的 `saga-infra` 连接，并在 `saga.discovery` 中设置 `qualifier: saga-infra`；新 Saga 使用业务别名，能力登记、续租及结果回传使用恢复别名。固定 URL 无需 qualifier，显式 qualifier 失败不会切换环境。Kubernetes adapter 只读，由部署方提供原生 Service 或受信代理。[发现配置](https://github.com/nasa-runtime/saga-server/blob/release/docs/discovery.md)包含完整客户端 YAML。

## 其它部署与运维命令

### 创建协调数据库

由 DBA 首次创建专用库，二选一；已有数据库保留数据和账号。密码特殊字符在 URL 中编码，网络、TLS、高可用和备份由部署方管理。

```sh
mysql --host=mysql.internal --port=3306 --user=db_admin --password <<'SQL'
CREATE DATABASE saga_control CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'saga_user'@'%' IDENTIFIED BY 'REPLACE_WITH_DATABASE_PASSWORD';
GRANT ALL PRIVILEGES ON saga_control.* TO 'saga_user'@'%';
SQL
```

```sh
psql 'host=postgres.internal port=5432 dbname=postgres user=db_admin' --password <<'SQL'
CREATE ROLE saga_user LOGIN PASSWORD 'REPLACE_WITH_DATABASE_PASSWORD';
CREATE DATABASE saga_control OWNER saga_user;
SQL
```

运行账号需要本库的结构检查、DDL 和读写权限。MySQL 首次触发器创建还受服务器 binlog 策略限制。

### MySQL 首次初始化与触发器权限

开启 binlog 且 `log_bin_trust_function_creators=0` 时，单库 `GRANT ALL` 可能不足以创建审计触发器，应用会拒绝 Ready。DBA 先核对：

```sh
mysql --host=mysql.internal --port=3306 --user=db_admin --password \
  --execute='SELECT @@log_bin, @@log_bin_trust_function_creators;'
```

该策略下，用有权创建触发器的稳定模式管理账号初始化空库，再切换 `saga_user`。以下仅用于首次部署、尚无流量和其它协调副本；`.env` 不设 profile，`application.yml` 只含授权及运行策略。先准备密钥和配置，并执行 `export SAGA_IMAGE=nasaruntime/saga-server:1.0.0`：

```sh
umask 077
cat > mysql-bootstrap.env <<'ENV'
SAGA_DATABASE_DRIVER=mysql
SAGA_DATABASE_URL=mysql://schema_admin:URL_ENCODED_PASSWORD@mysql.internal:3306/saga_control
ENV
chmod 600 mysql-bootstrap.env
(
  set -e
  docker run --detach --name saga-schema-init \
    --stop-timeout 70 --read-only --cap-drop ALL --security-opt no-new-privileges \
    --env-file ./.env --env-file ./mysql-bootstrap.env \
    --env SAGA_REPLICA_ID=saga-schema-init \
    --mount "type=bind,src=$PWD/application.yml,dst=/etc/saga-server/application.yml,readonly" \
    --publish 127.0.0.1:12079:2070 \
    "$SAGA_IMAGE"
  curl --fail --retry 60 --retry-connrefused --retry-delay 1 --retry-max-time 120 \
    --max-time 2 http://127.0.0.1:12079/readyz
  docker stop --time 70 saga-schema-init
  docker rm saga-schema-init
  rm mysql-bootstrap.env
)
```

初始化容器是完整协调进程，Ready 后需显式停止。失败时检查 `docker logs saga-schema-init` 并由 DBA 处理，不绕过 schema 门禁。保留触发器 `DEFINER` 对应数据库账号及所需表权限；仅删除临时环境文件。正式容器继续使用 `.env` 中的单库账号。

已有集群升级由 DBA 按维护流程处理结构，不重复套用首次初始化命令。数据库平台也可由 DBA 管理允许触发器创建的参数策略；应用不自动改变全局设置。[MySQL 权限规则](https://dev.mysql.com/doc/refman/8.4/en/stored-programs-logging.html)。

### PostgreSQL 与固定 HTTP 入口

在同一个 `.env` 中替换以下两项；固定 HTTP 模式不设置 `APP_PROFILE`：

```dotenv
SAGA_DATABASE_DRIVER=postgresql
SAGA_DATABASE_URL=postgres://saga_user:URL_ENCODED_PASSWORD@postgres.internal:5432/saga_control
```

```sh
docker run --detach --name saga-postgres \
  --restart unless-stopped --stop-timeout 70 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --env-file ./.env \
  --mount "type=bind,src=$PWD/application.yml,dst=/etc/saga-server/application.yml,readonly" \
  --publish 127.0.0.1:2070:2070 \
  "$SAGA_IMAGE"
curl --fail http://127.0.0.1:2070/healthz
curl --fail http://127.0.0.1:2070/readyz
docker logs --tail 100 saga-postgres
```

PostgreSQL 配合 Nacos/Consul 时，在同一个 `.env` 中保留对应注册中心参数即可。同一集群所有副本连接同一协调库。

### Nacos 与 Consul 混合发布

在同一个 `.env` 中填写两套 Nacos/Consul 地址、凭据和发布端点，删除 `APP_PROFILE`。将[混合配置](https://github.com/nasa-runtime/saga-server/blob/release/examples/config/discovery-mixed.yml)中的整个 `discovery` 段合并到 `application.yml`，保留已有 `secrets` 和 `saga`；已有 `discovery` 时整体替换，不能出现重复根键。配置仍只有一份 `.env` 和一份业务 YAML。

```sh
docker run --detach --name saga-mixed \
  --restart unless-stopped --stop-timeout 70 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --env-file ./.env \
  --env SECONDARY_REGISTER_IP=192.168.20.20 --env SECONDARY_REGISTER_PORT=22070 \
  --mount "type=bind,src=$PWD/application.yml,dst=/etc/saga-server/application.yml,readonly" \
  --publish 192.168.10.20:12070:2070 --publish 192.168.20.20:22070:2070 \
  "$SAGA_IMAGE"
curl --fail http://192.168.10.20:12070/readyz
curl --fail http://192.168.10.20:12070/discovery/eligible/primary-recovery
curl --fail http://192.168.20.20:22070/discovery/eligible/secondary-recovery
docker logs --tail 100 saga-mixed
```

从两个网络核对发现记录与连通性。

### 两个协调副本共享数据库

固定 HTTP 模式，两副本共享数据库、信任配置和分页密钥，分别使用稳定身份；与单实例模式择一：

```sh
docker run --detach --name saga-server-0 \
  --restart unless-stopped --stop-timeout 70 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --env-file ./.env --env SAGA_REPLICA_ID=saga-server-0 \
  --mount "type=bind,src=$PWD/application.yml,dst=/etc/saga-server/application.yml,readonly" \
  --publish 127.0.0.1:12070:2070 \
  "$SAGA_IMAGE"
docker run --detach --name saga-server-1 \
  --restart unless-stopped --stop-timeout 70 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --env-file ./.env --env SAGA_REPLICA_ID=saga-server-1 \
  --mount "type=bind,src=$PWD/application.yml,dst=/etc/saga-server/application.yml,readonly" \
  --publish 127.0.0.1:12071:2070 \
  "$SAGA_IMAGE"
curl --fail http://127.0.0.1:12070/readyz
curl --fail http://127.0.0.1:12071/readyz
docker stats --no-stream saga-server-0 saga-server-1
```

跨宿主机分别运行一条命令并使用受控内网 IP。基础 Compose 使用固定身份和端口，不直接 `--scale`。启用发现时，各副本使用独立可达端点，Consul agent 固定，避免记录冲突。

### 自定义端口、指标与文件日志

仅改变宿主机端口时保留内部 2070。改变内部监听端口需同步健康检查、注册端口和抓取目标：

```sh
docker run --detach --name saga-custom-port \
  --restart unless-stopped --stop-timeout 70 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --env-file ./.env --env APP__SERVER__PORT=2080 \
  --mount "type=bind,src=$PWD/application.yml,dst=/etc/saga-server/application.yml,readonly" \
  --publish 127.0.0.1:12080:2080 --publish 127.0.0.1:9464:9464 \
  --health-cmd='wget -q -O /dev/null http://127.0.0.1:2080/readyz || exit 1' \
  "$SAGA_IMAGE"
curl --fail http://127.0.0.1:12080/readyz
curl --fail http://127.0.0.1:12080/_nasa/saga/metrics
curl --fail http://127.0.0.1:9464/metrics
```

文件日志的目录权限、只读配置与可写挂载见上方[配置与文件日志挂载](#配置与文件日志挂载)。

私钥及环境文件仅部署账号可读，配置 YAML 允许 UID 10001 读取。不要输出包含环境变量的完整 `docker inspect`。

### 状态检查与计划维护

替换为实际容器名：

```sh
docker ps --filter name=saga-server
docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' saga-server
docker logs --since 10m --tail 200 saga-server
docker stats --no-stream saga-server
```

计划维护时先摘流、排空，再停止；保留原数据库、配置、密钥和身份：

```sh
docker stop --time 70 saga-server
docker start saga-server
curl --fail http://127.0.0.1:2070/readyz
```

更换镜像前备份数据库并确认结构兼容性。先拉取目标 digest，再摘流、停止旧容器：

```sh
export SAGA_IMAGE='nasaruntime/saga-server@sha256:REPLACE_WITH_TARGET_MANIFEST_DIGEST'
docker pull "$SAGA_IMAGE"
docker stop --time 70 saga-server
docker rm saga-server
```

重新执行所选场景的完整启动命令，确认业务与恢复入口后恢复流量。回退也要确认旧程序兼容当前结构；多副本逐个替换，单副本有维护窗口。新增流程不执行停机命令。

Compose 在相同维护条件下更新指定服务：

```sh
docker compose pull saga-server
docker compose up -d --no-deps saga-server
docker compose ps
docker compose logs --tail 100 saga-server
```

监控 Compose 使用 `saga-monitoring` 和 `docker/monitoring/compose.yml`，仅更新协调服务并保留监控数据卷。

## 从业务定义到事务结果

镜像没有内置业务流程。流程拥有方声明并签名发布完整定义，各参与方登记步骤合同和能力、实现持久幂等与补偿。Java/Go 需要完整协议适配，普通 REST 接口不能直接登记为步骤。

定义激活后，业务客户端按 [HTTP 签名协议](https://github.com/nasa-runtime/saga-server/blob/release/docs/integration.md#http-地址与认证)发送请求，基础路径默认是 `/_nasa/saga`：

1. 用 `order-worker` 和对应 `SAGA_WORKER_KEY` 调用 `GET /registry/definitions/system/order_checkout/1` 确认定义已激活。
2. 用具有 `start` 权限的 `order-api` 和对应 `SAGA_CLIENT_KEY` 调用 `POST /instances`。按[请求字段](https://github.com/nasa-runtime/saga-server/blob/release/docs/integration.md#发起与查询)提供稳定的业务身份与符合流程合同的输入。
3. 用具有 `read` 权限的 caller 调用 `GET /instances/system/order-1001` 查询结果。

每次调用生成新的时间戳、nonce 和签名，不能混用不同 caller 的密钥。`Committed`/`Duplicate` 只说明创建结果，业务终态另行查询。结果不明时保持相同业务身份和内容，以新时间戳、nonce 和签名有界重试。代理必须保留原路径、正文及 `x-saga-*` 头。

## 多副本与持续运行

副本共享数据库、服务身份、信任配置和分页密钥，副本 ID 唯一且重启稳定。MySQL Outbox 使用会话锁：冻结进程或半开网络不等于连接关闭，仍持锁时其它副本不能接管；恢复原进程或确认退出且会话关闭后才能继续投递。timer 租约不会解除该锁。PostgreSQL Outbox 使用持久 owner 租约与 fencing。Docker 健康检查本身不会终止无响应进程。

新业务只进入 Ready 副本。能力续租、定义同步与结果回传保持独立受信恢复通道，继续执行鉴权及事务门禁；不能因业务不就绪阻断全部 Registry 请求。注册 profile 可用 `/discovery/eligible/primary-recovery` 检查恢复资格，固定 URL 由平台保留恢复路径。

## 调用、恢复与观测

`/healthz` 检查存活，`/readyz` 检查业务资格；停机先撤销资格与注册，再排空，宽限期应大于 60 秒。

`9464/metrics` 是 nafana 应用、Outbox 和发现出口；`2070/_nasa/saga/metrics` 提供持久状态和生命周期分位数。五个固定阶段的耗时直方图共 85 条序列，重启后重新累计；持久分位数另由数据库计算。指标拒绝计数反映出口容量不足。只向监控网络开放，跨副本共享数据库数量不能直接相加。[监控语义](https://github.com/nasa-runtime/saga-server/blob/release/docs/monitoring.md)。

### Prometheus 与 Grafana 部署示例

监控 Compose 已包含协调器，与单独部署择一。从当前部署目录复制配置到源码根目录，复用同一数据库与身份；只在首次选择监控模式时执行，已有服务先按计划维护停止：

```sh
git clone --branch release https://github.com/nasa-runtime/saga-server.git saga-source
cp .env application.yml saga-source/
cd saga-source
export SAGA_IMAGE=nasaruntime/saga-server:1.0.0
export GRAFANA_ADMIN_PASSWORD='REPLACE_WITH_A_STRONG_PASSWORD'
docker compose -p saga-monitoring -f docker/monitoring/compose.yml up -d
docker compose -p saga-monitoring -f docker/monitoring/compose.yml ps
```

Grafana：`http://127.0.0.1:3000`，账号 `admin`，上述密码，仪表盘 `Saga / Saga Server`。Prometheus：`http://127.0.0.1:9090`。环境、集群、服务标签与抓取配置对齐，按同一数据库去重聚合。

### 常见状态

| 现象 | 检查内容 |
| --- | --- |
| 启动失败 | 导入配置、凭据、数据库可达性、触发器初始化权限及容器日志 |
| 存活但未就绪 | Catalog、能力续租、依赖和恢复通道 |
| 新流程无法创建 | 定义激活、租户/流程授权、步骤合同与端点 |
| HTTP 401 / 403 | 签名与时钟、身份及授权范围 |
| HTTP 409 | HTTP 重放、业务身份/内容/定义冲突 |
| HTTP 超时或 503 | 保持原业务身份查询，或重新签名后有界重试 |
| 单个注册中心不可用 | 该 qualifier 的证据和目标状态，不跨环境回退 |

## 源码构建与镜像发布

[维护与发布命令](https://github.com/nasa-runtime/saga-server/blob/release/docker/PUBLISHING.md)说明源码构建、GitHub 配置、版本镜像和仓库说明更新。[完整中文说明](https://github.com/nasa-runtime/saga-server/blob/release/README.md)提供更多配置和架构细节。
