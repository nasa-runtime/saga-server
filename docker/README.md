# saga-server

独立 Saga 协调服务，提供动态流程定义、数据库持久恢复和多注册中心接入。Java、Go、Rust 业务可以保留各自的 Nacos 或 Consul，同一协调集群通过签名 HTTP 协议连接各环境的参与方，无需把业务服务迁入同一注册中心。

A standalone Saga orchestrator with workflow registration while the server stays running, durable recovery and multi-registry discovery. Already trusted business services add workflows without editing server YAML or restarting the coordinator, and can keep their own registry environments.

已接入的业务服务新增流程时，受管客户端主动上报签名定义、步骤能力及事务实例 ID，协调器保持运行，不需要修改服务端 YAML、热加载或重启。定义与实例保存在数据库中，YAML 管理基础设施、运行策略与信任范围。

- 镜像仓库：`nasaruntime/saga-server`，部署时选择明确版本或 digest。
- 平台：`linux/amd64`、`linux/arm64`；Alpine、musl，UID/GID `10001:10001`。
- 持久存储：MySQL 或 PostgreSQL，数据库需要预先创建。
- 许可证：MIT OR Apache-2.0。
- [源码与完整配置](https://github.com/nasa-runtime/saga-server)、[Dockerfile](https://github.com/nasa-runtime/saga-server/blob/release/docker/Dockerfile)。

## 运行架构与边界

协调状态、Inbox、Outbox、timer、流程目录和审计共用数据库。创建事务与首步命令持久化保持原子性；投递至少一次，参与方必须实现持久幂等和业务补偿。副本共享数据库，租约与 fencing 限制失权推进；副本身份必须唯一且重启稳定。

Nacos、Consul 只负责入口定位。具名 `qualifier` 不跨环境回退，业务入口与能力续租、结果回传的恢复入口分别管理。注册中心不复制 Saga 数据，不代替租户授权，也不保证参与方网络可达。协调器与参与方必须双向可达。

本镜像只装配 HTTP 协调角色，不执行业务步骤，不提供跨服务 ACID 或物理 exactly-once；gRPC、Kafka 和 Redis Streams 适配器未装配。Java、Go 参与方仍需实现完整的 Saga 协议，普通 REST 接口不能直接登记为步骤。

## 运行中接入新流程

流程拥有方发布包含 `workflow`、`definition_version` 和完整步骤合同的签名定义；各参与方登记可达能力并续租。动态 Catalog 持久化并同步这些事实，满足 `validated` 激活策略后，发起方携带 `saga_id` 和业务输入创建实例。定义名称与版本标识流程，`saga_id` 标识一次执行，服务端 YAML 不保存业务步骤清单或事务 ID。

业务服务可独立部署新流程、新步骤及新定义版本，既有实例继续使用冻结的定义版本和摘要。新流程须沿用已授权的身份、租户、公钥和网络范围；新增信任范围仍需调整部署配置。定义未激活时不能创建实例，`/readyz` 成功不能替代指定流程的状态检查。接入顺序与权限见[动态流程接入](https://github.com/nasa-runtime/saga-server/blob/release/docs/integration.md#流程动态上报与服务端持续运行)。

以下终端命令使用 Bash，所有地址和凭据占位值均需按实际环境填写。

## 配置与启动

首次使用 MySQL 时先核对[审计触发器初始化权限](#mysql-首次初始化与触发器权限)。普通运行账号的单库权限可能不足以执行首次触发器创建，下面提供 DBA 初始化后切换运行账号的完整命令。

主配置位于 `/app/zcf/application.yml`，导入 `${SAGA_YML:/etc/saga-server/*.yml}`。文件按自然名称顺序合并，后者覆盖前者，列表整体替换。缺少导入文件、凭据或必填配置时拒绝启动。配置变更需要重启，动态流程定义和能力租约独立同步。

准备本地目录，将[授权模板](https://github.com/nasa-runtime/saga-server/blob/release/examples/config/10-security.yml)保存为 `deploy-local/config/10-security.yml`，按实际接入身份配置 caller、租户、参与方地址和凭据映射。Registry caller 必须声明允许的 workflow 范围。

模板为可信定义管理方使用 `workflows: ["*"]`，允许其在显式授权的租户内管理新增流程，不逐个预置名称。此范围不按流程名称隔离，流程归属检查仍生效，仅适用于可信流程拥有方；身份认证、签名校验和网络白名单继续生效。新增不受信身份、公钥或网络范围仍需维护信任配置，具体流程和步骤由业务侧动态发布。

```sh
mkdir -p deploy-local/config
curl --fail --location \
  https://raw.githubusercontent.com/nasa-runtime/saga-server/release/examples/config/10-security.yml \
  --output deploy-local/config/10-security.yml
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

每个 HMAC 密钥分别使用 `openssl rand -hex 32` 生成。定义公钥为 Base64 编码的 SPKI DER，流程拥有方保管对应 PKCS8 DER 私钥，协调器只接收公钥。以下在本地生成密钥；将最后一条命令的输出填入 `SAGA_DEFINITION_PUBLIC_KEY`，私钥不能挂载给协调器。

```sh
umask 077
openssl genpkey -algorithm ED25519 -out deploy-local/definition-private.pem
openssl pkey -in deploy-local/definition-private.pem -pubout -outform DER -out deploy-local/definition-public.der
openssl base64 -A -in deploy-local/definition-public.der
```

参与方需要签名私钥时，由私钥持有方执行 `openssl pkcs8 -topk8 -nocrypt -in deploy-local/definition-private.pem -outform DER -out deploy-local/definition-private.der`，再用 `openssl base64 -A -in deploy-local/definition-private.der` 取得 PKCS8 DER 的 Base64 文本，仅交给流程拥有方。具体权限和协议见[业务接入](https://github.com/nasa-runtime/saga-server/blob/release/docs/integration.md)。

运行账号需要组件初始化所需的 DDL 权限及持久表读写权限，数据库须预先创建。切换 PostgreSQL 时在同一环境文件替换以下两行，其余启动命令相同：

```dotenv
SAGA_DATABASE_DRIVER=postgresql
SAGA_DATABASE_URL=postgres://saga_user:URL_ENCODED_PASSWORD@postgres.internal:5432/saga_control
```

```sh
chmod 600 deploy-local/saga.env
export SAGA_IMAGE=nasaruntime/saga-server:1.0.0
docker pull "$SAGA_IMAGE"
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

### 使用 Docker Compose

基础 Compose 连接已有数据库，复用上述 `deploy-local` 目录；无需安装 Rust。与 `docker run` 二选一，避免重复副本身份及宿主机端口冲突：

```sh
mkdir -p docker
curl --fail --location \
  https://raw.githubusercontent.com/nasa-runtime/saga-server/release/docker/compose.yml \
  --output docker/compose.yml
docker compose -p saga -f docker/compose.yml pull
docker compose -p saga -f docker/compose.yml up -d
docker compose -p saga -f docker/compose.yml ps
docker compose -p saga -f docker/compose.yml logs --tail 100 saga-server
curl --fail http://127.0.0.1:2070/readyz
```

挂载目录与 YAML 必须允许 UID 10001 读取。只在计划维护或升级时执行 `docker compose -p saga -f docker/compose.yml stop`；重新启动时保留原数据库、服务身份、副本身份及信任配置。新增业务流程由业务方动态上报，不需要停止协调器。

## Nacos、Consul 与多注册中心

默认关闭注册发现，调用方可使用固定 HTTP URL。启用单套 Nacos 时，创建独立的 `deploy-local/nacos.env`：

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

将本段变量保存为 `deploy-local/nacos.env`，基础数据库和密钥继续使用 `deploy-local/saga.env`。基础文件不设置 `APP_PROFILE`，授权目录不混入其它发现配置。以下为该场景的完整启动及检查命令；各模式在首次部署时择一，不同时占用示例端口。

```sh
docker run --detach --name saga-nacos \
  --restart unless-stopped --stop-timeout 70 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
  --env-file ./deploy-local/saga.env \
  --env-file ./deploy-local/nacos.env \
  --mount "type=bind,src=$PWD/deploy-local/config,dst=/etc/saga-server,readonly" \
  --publish 192.168.10.20:12070:2070 \
  "$SAGA_IMAGE"
docker logs --tail 100 saga-nacos
curl --fail http://192.168.10.20:12070/readyz
curl --fail http://192.168.10.20:12070/discovery/eligible/primary-recovery
```

对应端口映射改为 `192.168.10.20:12070:2070`。Nacos 使用 Nacos 3 HTTP API，不需要 SDK gRPC 端口。默认发布 `saga-server` 和 `saga-server-recovery`；Saga 身份及映射端点 metadata 由框架生成，不能用手工同名注册代替。

双 Nacos 保留第一套变量，将 `APP_PROFILE` 改为 `multi-nacos`，再增加第二套配置：

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

将本段变量保存为 `deploy-local/secondary.env`，基础数据库和密钥继续使用 `deploy-local/saga.env`。基础文件不设置 `APP_PROFILE`，授权目录不混入其它发现配置。以下为该场景的完整启动及检查命令；各模式在首次部署时择一，不同时占用示例端口。

```sh
docker run --detach --name saga-multi-nacos \
  --restart unless-stopped --stop-timeout 70 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
  --env-file ./deploy-local/saga.env \
  --env-file ./deploy-local/nacos.env \
  --env-file ./deploy-local/secondary.env \
  --mount "type=bind,src=$PWD/deploy-local/config,dst=/etc/saga-server,readonly" \
  --publish 192.168.10.20:12070:2070 \
  --publish 192.168.20.20:22070:2070 \
  "$SAGA_IMAGE"
docker logs --tail 100 saga-multi-nacos
curl --fail http://192.168.10.20:12070/readyz
curl --fail http://192.168.10.20:12070/discovery/eligible/primary-recovery
curl --fail http://192.168.20.20:22070/discovery/eligible/secondary-recovery
```

容器或网关提供两条到同一 listener 的映射，例如 `192.168.10.20:12070:2070` 与 `192.168.20.20:22070:2070`；IP 必须属于宿主机或由受信网关提供。两套连接分别名为 `primary`、`secondary`，各自发布普通与恢复入口，共享数据库事实。

单 Consul 使用以下变量替换原 profile 和发布端点；agent 地址必须固定到管理本副本记录的 agent：

```dotenv
APP_PROFILE=consul
CONSUL_API_ADDR=http://consul.internal:8500
CONSUL_AGENT_ADDR=http://consul-agent.internal:8500
CONSUL_DATACENTER=dc1
CONSUL_TOKEN=YOUR_CONSUL_TOKEN
SAGA_REGISTER_IP=192.168.10.20
SAGA_REGISTER_PORT=12070
```

将本段变量保存为 `deploy-local/consul.env`，基础数据库和密钥继续使用 `deploy-local/saga.env`。基础文件不设置 `APP_PROFILE`，授权目录不混入其它发现配置。以下为该场景的完整启动及检查命令；各模式在首次部署时择一，不同时占用示例端口。

```sh
docker run --detach --name saga-consul \
  --restart unless-stopped --stop-timeout 70 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
  --env-file ./deploy-local/saga.env \
  --env-file ./deploy-local/consul.env \
  --mount "type=bind,src=$PWD/deploy-local/config,dst=/etc/saga-server,readonly" \
  --publish 192.168.10.20:12070:2070 \
  "$SAGA_IMAGE"
docker logs --tail 100 saga-consul
curl --fail http://192.168.10.20:12070/readyz
curl --fail http://192.168.10.20:12070/discovery/eligible/primary-recovery
```

Nacos/Consul 混合部署时不设置 `APP_PROFILE`，将[混合配置](https://github.com/nasa-runtime/saga-server/blob/release/examples/config/discovery-mixed.yml)保存到挂载目录，再填写两套凭据和端点。Kubernetes adapter 只读，部署方提供原生 Service 或受信代理入口。

Rust 业务可保留自己的 `primary` 连接，另外配置名为 `saga-infra` 的协调连接，在 `saga.discovery` 中用 `qualifier: saga-infra` 选择它。新 Saga 使用普通服务别名，能力登记、续租与结果回传使用恢复别名。固定 HTTP 地址无需 qualifier；显式 qualifier 不可用时不会切到其它环境。[完整发现配置](https://github.com/nasa-runtime/saga-server/blob/release/docs/discovery.md#qualifier-与业务方接入)包含可合并的客户端 YAML。

## 其它部署与运维命令

### 创建协调数据库

由数据库管理员在已有 MySQL 或 PostgreSQL 上执行，二选一。以下只适用于首次创建专用协调库，已有数据库保留原数据和账号，不重复建库。替换密码占位值，并在连接 URL 中对特殊字符进行 URL 编码。

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

正式运行账号需要在协调库中建表、检查结构和读写持久状态，不需要其它业务库的权限。MySQL 首次创建审计触发器还受 binlog 策略约束，见下一节。数据库访问网段、防火墙、TLS、高可用与备份由部署方配置。

### MySQL 首次初始化与触发器权限

协调库包含审计触发器。MySQL 开启 binlog 且 `log_bin_trust_function_creators=0` 时，仅有单库权限的账号可能无法创建触发器，启动会在 schema 检查阶段失败；`GRANT ALL ON saga_control.*` 不包含服务器级权限。由 DBA 核对当前实例策略：

```sh
mysql --host=mysql.internal --port=3306 --user=db_admin --password \
  --execute='SELECT @@log_bin, @@log_bin_trust_function_creators;'
```

在该策略下，由 DBA 使用有权创建触发器的模式管理账号先初始化空的专用协调库，再使用 `saga_user` 启动正式服务。以下只用于首次部署，前提是尚无业务流量、没有其它协调副本运行，基础 `saga.env` 不设置 `APP_PROFILE`，配置目录只包含授权与运行策略。先完成前文的镜像拉取、密钥和配置准备，将下列数据库连接写入只供初始化使用的文件：

```sh
umask 077
cat > deploy-local/mysql-bootstrap.env <<'ENV'
SAGA_DATABASE_DRIVER=mysql
SAGA_DATABASE_URL=mysql://schema_admin:URL_ENCODED_PASSWORD@mysql.internal:3306/saga_control
ENV
chmod 600 deploy-local/mysql-bootstrap.env
(
  set -e
  docker run --detach --name saga-schema-init \
    --stop-timeout 70 --read-only --cap-drop ALL --security-opt no-new-privileges \
    --env-file ./deploy-local/saga.env --env-file ./deploy-local/mysql-bootstrap.env \
    --env SAGA_REPLICA_ID=saga-schema-init \
    --mount "type=bind,src=$PWD/deploy-local/config,dst=/etc/saga-server,readonly" \
    --publish 127.0.0.1:12079:2070 \
    "$SAGA_IMAGE"
  curl --fail --retry 60 --retry-connrefused --retry-delay 1 --retry-max-time 120 \
    --max-time 2 http://127.0.0.1:12079/readyz
  docker stop --time 70 saga-schema-init
  docker rm saga-schema-init
  rm deploy-local/mysql-bootstrap.env
)
```

成功后按所选场景启动正式容器，`saga.env` 仍使用仅具单库权限的 `saga_user`。上面的容器是完整协调进程，通过 Ready 表示初始化完成；它不会自动退出。失败时检查 `docker logs saga-schema-init`，由 DBA 处理数据库原因后再继续，不能绕过 schema 门禁。初始化账号会成为触发器的 `DEFINER`，必须保留该数据库账号及执行触发器所需的表权限；删除临时环境文件不等于删除该账号。

后续升级若需要改变审计触发器，由 DBA 按维护流程处理结构并核对 `DEFINER`，不要把上述首次初始化命令用于已有业务集群。若数据库平台允许应用直接创建触发器，也可由 DBA 管理相应的实例参数或托管数据库参数组；本项目不自动修改服务器全局设置。权限规则见 [MySQL binary logging 与触发器](https://dev.mysql.com/doc/refman/8.4/en/stored-programs-logging.html)。


### PostgreSQL 与固定 HTTP 入口

将下面两项单独保存为 `deploy-local/postgres.env`，基础环境文件继续保留密钥和稳定身份，不设置 discovery profile。配置目录只包含授权和运行策略，不加入 Nacos/Consul 发现目标。

```dotenv
SAGA_DATABASE_DRIVER=postgresql
SAGA_DATABASE_URL=postgres://saga_user:URL_ENCODED_PASSWORD@postgres.internal:5432/saga_control
```

```sh
docker run --detach --name saga-postgres \
  --restart unless-stopped --stop-timeout 70 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --env-file ./deploy-local/saga.env --env-file ./deploy-local/postgres.env \
  --mount "type=bind,src=$PWD/deploy-local/config,dst=/etc/saga-server,readonly" \
  --publish 127.0.0.1:2070:2070 \
  "$SAGA_IMAGE"
curl --fail http://127.0.0.1:2070/healthz
curl --fail http://127.0.0.1:2070/readyz
docker logs --tail 100 saga-postgres
```

数据库与注册中心相互独立。PostgreSQL 也可配合单 Nacos、双 Nacos 或 Consul：在对应启动命令的其它环境文件之后追加 `--env-file ./deploy-local/postgres.env`。同一协调集群所有副本必须使用同一个协调数据库。

### Nacos 与 Consul 混合发布

先填写前文的 `nacos.env` 和 `consul.env`。使用独立挂载目录，去掉两份文件的 profile 后合并变量，避免叠加内置目标。基础 `saga.env` 不设置 `APP_PROFILE`。本例使用前文中的两条内网 IP 映射。

```sh
mkdir -p deploy-local/mixed-config
cp deploy-local/config/10-security.yml deploy-local/mixed-config/10-security.yml
curl --fail --location \
  https://raw.githubusercontent.com/nasa-runtime/saga-server/release/examples/config/discovery-mixed.yml \
  --output deploy-local/mixed-config/30-discovery.yml
umask 077
grep -v '^APP_PROFILE=' deploy-local/nacos.env > deploy-local/mixed.env
grep -v '^APP_PROFILE=' deploy-local/consul.env >> deploy-local/mixed.env
chmod 600 deploy-local/mixed.env
docker run --detach --name saga-mixed \
  --restart unless-stopped --stop-timeout 70 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --env-file ./deploy-local/saga.env --env-file ./deploy-local/mixed.env \
  --env SECONDARY_REGISTER_IP=192.168.20.20 --env SECONDARY_REGISTER_PORT=22070 \
  --mount "type=bind,src=$PWD/deploy-local/mixed-config,dst=/etc/saga-server,readonly" \
  --publish 192.168.10.20:12070:2070 --publish 192.168.20.20:22070:2070 \
  "$SAGA_IMAGE"
curl --fail http://192.168.10.20:12070/readyz
curl --fail http://192.168.10.20:12070/discovery/eligible/primary-recovery
curl --fail http://192.168.20.20:22070/discovery/eligible/secondary-recovery
docker logs --tail 100 saga-mixed
```

映射 IP 必须属于当前宿主机，或通过受信网关提供等效路径。上述探针只说明本地资格，还应从两个业务网络检查发现记录与 HTTP 连通性。两套 Nacos 使用同一服务地址、不同 namespace/group 时，沿用双 Nacos 命令并分别填写对应范围与凭据；两个目标不能覆盖同一注册记录。

### 两个协调副本共享数据库

以下使用固定 HTTP 模式。两副本共享数据库、信任配置和分页密钥，分别使用稳定的副本身份；基础环境文件不启用发现配置。与前面的单实例命令择一，不重复运行相同身份。

```sh
docker run --detach --name saga-server-0 \
  --restart unless-stopped --stop-timeout 70 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --env-file ./deploy-local/saga.env --env SAGA_REPLICA_ID=saga-server-0 \
  --mount "type=bind,src=$PWD/deploy-local/config,dst=/etc/saga-server,readonly" \
  --publish 127.0.0.1:12070:2070 \
  "$SAGA_IMAGE"
docker run --detach --name saga-server-1 \
  --restart unless-stopped --stop-timeout 70 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --env-file ./deploy-local/saga.env --env SAGA_REPLICA_ID=saga-server-1 \
  --mount "type=bind,src=$PWD/deploy-local/config,dst=/etc/saga-server,readonly" \
  --publish 127.0.0.1:12071:2070 \
  "$SAGA_IMAGE"
curl --fail http://127.0.0.1:12070/readyz
curl --fail http://127.0.0.1:12071/readyz
docker stats --no-stream saga-server-0 saga-server-1
```

跨宿主机部署时分别执行一条命令，并使用各自的受控内网 IP。负载均衡器必须区分业务与恢复通道，不能因普通业务未就绪而阻断全部能力登记。固定副本身份和宿主机端口的基础 Compose 不直接使用 `--scale`；按副本准备独立身份与端口。启用 Nacos/Consul 时，还需分别配置可达发布端点与固定 agent，避免注册记录冲突。

### 自定义端口、指标与文件日志

只改变宿主机映射端口时保留内部 `2070` 即可。确需改变内部监听端口时，同时覆盖 Docker 健康检查，并同步注册端口和 Prometheus 抓取目标：

```sh
docker run --detach --name saga-custom-port \
  --restart unless-stopped --stop-timeout 70 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --env-file ./deploy-local/saga.env --env APP__SERVER__PORT=2080 \
  --mount "type=bind,src=$PWD/deploy-local/config,dst=/etc/saga-server,readonly" \
  --publish 127.0.0.1:12080:2080 --publish 127.0.0.1:9464:9464 \
  --health-cmd='wget -q -O /dev/null http://127.0.0.1:2080/readyz || exit 1' \
  "$SAGA_IMAGE"
curl --fail http://127.0.0.1:12080/readyz
curl --fail http://127.0.0.1:12080/_nasa/saga/metrics
curl --fail http://127.0.0.1:9464/metrics
```

需要文件日志时，先创建 UID/GID 10001 可写目录，再运行下面的完整命令；与控制台日志模式择一，配置目录仍为只读。

```sh
sudo install -d -o 10001 -g 10001 -m 0750 deploy-local/logs
docker run --detach --name saga-file-log \
  --restart unless-stopped --stop-timeout 70 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --env-file ./deploy-local/saga.env --env SAGA_LOG_PATH=/var/log/saga-server \
  --mount "type=bind,src=$PWD/deploy-local/config,dst=/etc/saga-server,readonly" \
  --mount "type=bind,src=$PWD/deploy-local/logs,dst=/var/log/saga-server" \
  --publish 127.0.0.1:2070:2070 \
  "$SAGA_IMAGE"
curl --fail http://127.0.0.1:2070/readyz
docker logs --tail 100 saga-file-log
```

以上目录授权命令用于 Linux 宿主机；Docker Desktop 的挂载授权还需符合其文件共享设置。环境文件与私钥仅允许部署账号读取，配置 YAML 则必须允许容器 UID 10001 读取。不要输出包含环境变量的完整 `docker inspect` 结果来排查凭据。

### 状态检查与计划维护

将示例容器名 `saga-server` 换为实际运行的名称：

```sh
docker ps --filter name=saga-server
docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' saga-server
docker logs --since 10m --tail 200 saga-server
docker stats --no-stream saga-server
```

只在计划维护时摘流并停止服务；原容器重新启动时保留数据库、配置、密钥和副本身份：

```sh
docker stop --time 70 saga-server
docker start saga-server
curl --fail http://127.0.0.1:2070/readyz
```

替换镜像前完成数据库备份和数据结构兼容性确认。先拉取目标镜像，再从普通业务入口摘除待更新副本、排空请求并停止该副本。目标 digest 由部署方选择：

```sh
export SAGA_IMAGE='nasaruntime/saga-server@sha256:REPLACE_WITH_TARGET_MANIFEST_DIGEST'
docker pull "$SAGA_IMAGE"
docker stop --time 70 saga-server
docker rm saga-server
```

随后重新执行已选场景的完整 `docker run` 命令，保留原环境文件、挂载和副本身份，确认业务与恢复入口后恢复流量。回退使用同样步骤及已确认兼容的旧 digest，不能假设旧程序一定支持升级后的数据结构。多副本逐个替换，单副本有维护窗口；新增业务流程不执行这些停止命令。

Compose 部署在同样的维护与摘流条件下更新指定服务：

```sh
docker compose -p saga -f docker/compose.yml pull saga-server
docker compose -p saga -f docker/compose.yml up -d --no-deps saga-server
docker compose -p saga -f docker/compose.yml ps
docker compose -p saga -f docker/compose.yml logs --tail 100 saga-server
```

监控 Compose 使用项目名 `saga-monitoring` 和文件 `docker/monitoring/compose.yml` 执行相同的服务级操作。仅更新 `saga-server`，保留 Prometheus 与 Grafana 数据卷；不要用删除数据卷代替升级。

## 从业务定义到事务结果

本镜像没有内置业务工作流。先按[参与方接入](https://github.com/nasa-runtime/saga-server/blob/release/docs/integration.md#参与方与流程拥有方)部署业务服务：流程拥有方使用 `#[nasa::saga_workflow]` 声明完整定义，受管客户端签名发布；各步骤参与方持久化本地业务事实并登记、续租能力。定义和步骤合同满足激活策略后才能创建实例。Java、Go 服务需要相应的 Saga 协议适配层，普通 REST 接口不能直接作为步骤。

以下假设已动态发布 `order_checkout` 定义版本 `1`，首步骤接受 `order_id` 和 `quantity`。下载 Python 3 标准库示例，并先用 `order-worker` 和其 `SAGA_WORKER_KEY` 查询定义；交互输入的密钥不回显：

```sh
mkdir -p examples
curl --fail --location \
  https://raw.githubusercontent.com/nasa-runtime/saga-server/release/examples/saga-http.py \
  --output examples/saga-http.py
export SAGA_BASE_URL=http://127.0.0.1:2070/_nasa/saga
export SAGA_HTTP_PRODUCER=order-worker
read -r -s SAGA_HTTP_KEY
export SAGA_HTTP_KEY
python3 examples/saga-http.py definition \
  --tenant system --workflow order_checkout --definition-version 1
```

确认定义已激活后，将调用身份切换为 `order-api`，输入 `SAGA_CLIENT_KEY`，创建并查询事务：

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

示例仅发送一次请求，保留真实 HTTP 状态，不自动重试或跟随重定向。`Committed` 和 `Duplicate` 是创建结果，不能代替最终业务结果。超时或 503 后保留相同实例身份与输入，重新签名后查询或有界重试，不能生成另一个实例代替原事务。协议字段、签名格式及全部接口见[业务 API](https://github.com/nasa-runtime/saga-server/blob/release/docs/integration.md#发起与查询)。

## 多副本与持续运行

所有协调副本连接同一个数据库，保持相同逻辑服务身份、信任配置和分页密钥；分别设置 `SAGA_REPLICA_ID=saga-server-0`、`saga-server-1`，重启后保持原值。数据库和负载均衡器的高可用由部署方提供，多注册中心不复制数据库。

MySQL Outbox 的投递权绑定数据库会话锁。暂停进程或半开网络不等于会话断开，其他副本不能强抢仍被占用的锁；恢复原进程或确认原进程退出且其数据库会话关闭后才能继续投递，timer 租约不会解除该锁。PostgreSQL Outbox 使用带 fencing 的持久 owner 租约。恢复时间取决于实际后端与故障方式；Docker 健康检查本身不会终止无响应进程，部署平台必须提供对应的故障处置策略。

新业务流量只进入 `/readyz` 通过的副本；能力续租、定义同步和结果回传必须保留独立恢复通道。启用内置 discovery profile 时可用 `/discovery/eligible/primary-recovery` 检查恢复资格；固定 URL 部署保留受信恢复路径及平台停机摘流。不能因为参与能力过期而阻断全部 Registry 请求，否则参与方无法重新登记。恢复入口继续执行认证和事务门禁，不赋予新 Saga 越过业务就绪的权限。

## 调用、恢复与观测

业务方通过 `/_nasa/saga` 下的签名 HTTP API 发布定义、登记能力、创建和查询流程。HTTP 200 的 `Committed` 或 `Duplicate` 仅说明创建结果，业务终态另行查询。HTTP 签名覆盖实际 path 和原始 body，代理必须保留请求头、路径和正文。事务冲突或暂不可用可能返回 503；结果不明时保留相同业务身份与内容，使用新的时间戳、nonce 和签名进行有界退避重试。

`/healthz` 表示存活，`/readyz` 表示业务就绪。能力失效时普通入口可被撤出，恢复路径仍需允许受信续租和结果回传；恢复地址不会绕过鉴权或业务门禁。停机先撤销资格与注册，再排空资源，停止宽限期应大于 60 秒。

`9464/metrics` 提供 nafana 应用、Outbox 和发现指标，`2070/_nasa/saga/metrics` 提供持久 Saga 状态和生命周期分位数。只允许监控网络访问；多副本共享数据库指标按同一数据库去重，不能直接求和。阶段耗时直方图覆盖五个固定阶段，共 85 条序列；进程重启后重新累计。持久生命周期分位数另由数据库事实计算，指标拒绝计数用于识别出口容量不足。[监控配置](https://github.com/nasa-runtime/saga-server/blob/release/docs/monitoring.md)包含 Prometheus、Grafana、告警和聚合语义。

业务通信、配置与监控部署的完整说明：[中文](https://github.com/nasa-runtime/saga-server/blob/release/README.md)、[English](https://github.com/nasa-runtime/saga-server/blob/release/README.en.md)。

### Prometheus 与 Grafana 部署示例

监控 Compose 已包含协调服务，首次部署时与单独运行方式二选一。取得源码后，在仓库根目录准备同样的 `deploy-local/config` 与 `deploy-local/saga.env`：

```sh
git clone --branch release https://github.com/nasa-runtime/saga-server.git
cd saga-server
export SAGA_IMAGE=nasaruntime/saga-server:1.0.0
export GRAFANA_ADMIN_PASSWORD='REPLACE_WITH_A_STRONG_PASSWORD'
docker compose -p saga-monitoring -f docker/monitoring/compose.yml up -d
docker compose -p saga-monitoring -f docker/monitoring/compose.yml ps
```

Grafana 为 `http://127.0.0.1:3000`，账号 `admin`，密码为上述值，仪表盘为 `Saga / Saga Server`；Prometheus 为 `http://127.0.0.1:9090`。Compose 不创建业务数据库。环境、集群、服务标签要与抓取配置一致；共享数据库指标按相同数据库去重，不能把多副本数量直接相加。

### 常见状态

| 现象 | 检查内容 |
| --- | --- |
| 容器启动失败 | 导入文件、必填凭据、数据库可达性和初始化权限；`docker logs --tail 100 saga-server` |
| `/healthz` 成功但 `/readyz` 失败 | 动态目录、步骤能力续租、必要依赖和恢复入口是否仍可达 |
| 服务就绪但新流程无法创建 | 指定定义是否激活、tenant/workflow 授权、步骤合同和参与端点 |
| HTTP 401 / 403 | 分别检查签名与时钟、调用身份和授权范围 |
| HTTP 409 | 区分原 HTTP 请求重放与业务身份、内容、定义版本冲突 |
| HTTP 超时或 503 | 结果可能已经提交，保留原身份查询或重新签名后有界重试 |
| 单个注册中心不可用 | 核对该 qualifier 的证据与目标状态，不能依赖跨环境回退 |

## 源码构建与镜像发布

维护分支为 `master`，发布分支固定为 `release`。Git 版本标签与 `Cargo.toml` 中的软件版本一致，例如 `1.0.0`，不加 `v` 前缀。Build 工作流在 release 分支生成 `linux/amd64` 和 `linux/arm64` 镜像归档，不自动上传镜像。归档保留 3 天，过期后需要重新构建。

GitHub Actions 使用以下仓库配置：

| 类型 | 名称 | 用途 |
| --- | --- | --- |
| Variable | `DOCKERHUB_USERNAME` | 有目标仓库推送及更新仓库说明权限的账号 |
| Variable（可选） | `DOCKERHUB_NAMESPACE` | 默认 `nasaruntime`，无需配置；与镜像名及文档一致 |
| Secret | `DOCKERHUB_TOKEN` | 上述账号的访问凭据，不写入源码、环境样例或日志 |

先在 Docker Hub 的 `nasaruntime` 命名空间创建 Public 仓库 `saga-server`，确保匿名拉取和仓库说明读取可用。当前流程同时推送镜像并更新仓库说明，使用个人访问令牌（PAT），权限选择 `Repo Read, Write, Delete`（`repo:admin`），账号需要具有目标仓库的管理权限。在 Docker Home 的头像菜单进入 Account settings → Personal access tokens → Generate new token 创建，生成后将值保存到 GitHub 仓库的 `DOCKERHUB_TOKEN` Secret。权限范围和创建步骤见 [Docker Token 权限说明](https://docs.docker.com/security/access-tokens/reference/)与[个人令牌指南](https://docs.docker.com/security/access-tokens/personal-access-tokens/)。

最终源码与镜像内容确认后，为该提交创建版本标签。在 release 分支手工运行 `Publish Docker image`，提供成功 Build 的 `build_run_id` 以及两个归档的 `amd64_config_digest`、`arm64_config_digest`。摘要采用 `sha256:` 格式，来自各归档实际配置文件。工作流核对 `master`、`release`、版本标签与构建提交相同，核对归档和装载后镜像身份，再上传这两个既有镜像。支持直接指向该提交的轻量标签或附注标签；标签缺失或指向其它提交时停止。

发布先生成明确软件版本的多架构标签，例如 `nasaruntime/saga-server:1.0.0`，回读内容并更新仓库说明后，再使 `latest` 指向该版本。已有版本指向不同内容时拒绝覆盖，需要选择新的软件版本；镜像仓库无法读取或内容无法确认时停止。不会在发布阶段重建镜像替换已核对的归档。
