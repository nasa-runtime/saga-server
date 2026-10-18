# 多注册中心部署

`saga-server` 使用 NASA 的 `discovery` 生命周期组件。一个协调副本可以同时向多套 Nacos 或
Consul 发布入口；每个目标独立配置地址、凭据、服务名、可达 IP 和映射端口。协调状态始终属于
共享数据库，注册中心不承担 Saga 选主、状态复制或租户授权。

注册中心提供协调入口定位，Saga Registry 则通过业务 HTTP 协议接收定义与步骤能力，两者用途不同。已授权业务新增流程不需要增加 Nacos/Consul 注册目标，也不需要改动协调端配置或重启；完整定义、能力续租和实例创建顺序见[动态流程接入](integration.md#流程动态上报与服务端持续运行)。新增注册中心连接属于启动时加载的部署配置。

## 单 Nacos 与双 Nacos

`APP_PROFILE=nacos` 加载 [单 Nacos 配置](../zcf/application-nacos.yml)。Nacos 必须支持受管
adapter 使用的 Nacos 3 HTTP API；`NACOS_SERVER_ADDR` 填完整服务地址，例如
`http://nacos.internal:8848/nacos/`，不是控制台地址。此模式不使用 SDK gRPC 连接。
账号需要读取管理侧实例属性并进行所选服务的注册、心跳及注销。管理 API 与 client API 的鉴权
可独立启用；不能因为 client API 无需登录就省略管理取证所需的凭据。

`APP_PROFILE=multi-nacos` 加载 [双 Nacos 配置](../zcf/application-multi-nacos.yml)，变量如下：

| 配置 | primary | secondary |
| --- | --- | --- |
| HTTP 服务地址 | `NACOS_SERVER_ADDR` | `SECONDARY_NACOS_SERVER_ADDR` |
| namespace ID | `NACOS_NAMESPACE`，默认 public | `SECONDARY_NACOS_NAMESPACE`，默认 public |
| group | `NACOS_GROUP`，默认 SAGA_GROUP | `SECONDARY_NACOS_GROUP`，默认 SAGA_GROUP |
| 账号与密码 | `NACOS_USERNAME` / `NACOS_PASSWORD` | `SECONDARY_NACOS_USERNAME` / `SECONDARY_NACOS_PASSWORD` |
| 调用方可达 IP | `SAGA_REGISTER_IP` | `SECONDARY_REGISTER_IP` |
| 调用方可达端口 | `SAGA_REGISTER_PORT`，默认 2070 | `SECONDARY_REGISTER_PORT`，默认 2070 |

每个连接都有 `coordinator`、`recovery` 两个本地服务别名，分别绑定
`${SAGA_SERVICE_ID:saga-server}` 与 `${SAGA_SERVICE_ID:saga-server}-recovery`。每个副本向两处各注册
两个目标，使用同一逻辑 Saga 身份、各自可达的端点和由框架生成的 Saga metadata。

同集群不同 namespace/group 也使用两条连接。两个目标不得覆盖同一后端服务和 IP/端口的注册
记录；仅更换 Nacos cluster 不构成写入隔离。增加第三套环境时，在挂载配置中增加新的
`discovery.connections.<名称>` 及对应 `registrations`，无需增加业务循环或修改 main。

## Consul 与混合后端

`APP_PROFILE=consul` 加载 [Consul 配置](../zcf/application-consul.yml)，设置
`CONSUL_API_ADDR`、`CONSUL_AGENT_ADDR`、`CONSUL_DATACENTER`、可选 `CONSUL_TOKEN`，以及
`SAGA_REGISTER_IP` / `SAGA_REGISTER_PORT`。`agent_addr` 必须固定到管理本进程服务记录的 agent。
TTL 检查由当前本地资格驱动，不能把进程存活等同于业务可用。

混合 Nacos 与 Consul 时，将[混合配置](../examples/config/discovery-mixed.yml)中的
`discovery` 段合并到根目录 `application.yml`，保留已有 `secrets` 和 `saga`。若已有
`discovery` 则替换该段，不能出现重复根键；无需新增环境文件或挂载目录。

不要在容器环境文件中设置 `APP_PROFILE`，避免同时合并内置 profile 的目标。填入两个后端的
完整地址、凭据和调用方可达端点，例如：

```dotenv
NACOS_SERVER_ADDR=http://nacos.internal:8848/nacos/
NACOS_NAMESPACE=public
NACOS_GROUP=SAGA_GROUP
NACOS_USERNAME=YOUR_NACOS_USERNAME
NACOS_PASSWORD=YOUR_NACOS_PASSWORD
CONSUL_API_ADDR=http://consul.internal:8500
CONSUL_AGENT_ADDR=http://consul-agent.internal:8500
CONSUL_DATACENTER=dc1
CONSUL_TOKEN=YOUR_CONSUL_TOKEN
SAGA_REGISTER_IP=192.168.10.20
SAGA_REGISTER_PORT=12070
SECONDARY_REGISTER_IP=192.168.20.20
SECONDARY_REGISTER_PORT=22070
```

部署网络或代理须把两个可达端点分别转发到同一个副本的 HTTP listener。连接名为 `primary`
和 `consul-go`；注册名 `secondary-http`、`secondary-recovery` 通过 `qualifier: consul-go`
选择 Consul，不要求注册名与连接名相同。该示例沿用加载器支持的四个注册名，因此两个端口
环境变量会转换为数值。示例只增加发现配置，不替代数据源、Saga 身份和安全配置。

支持 Static/DNS 及 Kubernetes 只读发现，但不能为只读后端声明写侧注册目标。

## qualifier 与业务方接入

`qualifier` 是 `discovery.connections` 中的精确名称，不是 provider 类型、服务别名或 Nacos
cluster。默认名称是小写 `primary`；未知 qualifier 或选定连接无合法实例时拒绝调用，不切换到
另一套注册中心。连接配置不会自动使本进程注册，必须另行声明 `registrations`。

| 名称 | 所属范围与作用 |
| --- | --- |
| `qualifier` | 当前进程的连接名；协调端和调用端不必同名，但必须选择相应后端范围 |
| `service` / `service_name` | 分别用于 Saga 发现引用、注册目标；值都是选定连接内的服务别名 |
| 后端服务名 | 别名映射到的 Nacos 或 Consul 服务名，如 `saga-server-recovery` |
| `service_identity` | Saga 协议信任的逻辑身份；恢复服务名带后缀时，身份仍是 `saga-server` |
| `replica_identity` | 单个协调副本的稳定身份；同一集群各副本必须不同 |

Rust 参与方启用 `application`、`web`、`saga-runtime` 和对应的 `discovery-nacos` 或
`discovery-consul` feature，在 `#[nasa::application]` 中声明 `"discovery"`。业务自己的连接及注册
仍可放在 `primary`；增加用于查询协调器的连接，例如：

```yaml
discovery:
  enabled: true
  connections:
    saga-infra:
      provider: nacos
      nacos:
        server_addr: http://nacos-infra:8848/nacos/
        namespace: public
        group: SAGA_GROUP
        username: ${SAGA_NACOS_USERNAME}
        password: ${SAGA_NACOS_PASSWORD}
        services:
          coordinator: {name: saga-server}
          recovery: {name: saga-server-recovery}
saga:
  discovery:
    saga-coordinator:
      qualifier: saga-infra
      service: coordinator
      service_identity: saga-server
      address_policy_ref: saga-coordinators
    saga-recovery:
      qualifier: saga-infra
      service: recovery
      service_identity: saga-server
      address_policy_ref: saga-coordinators
  definition_catalog:
    registry_client:
      discovery_ref: saga-recovery
  transport:
    address_policies:
      saga-coordinators:
        http_schemes: [http]
        http_hosts: [192.168.10.20, 192.168.10.21]
        http_ports: [12070]
    command_result:
      http:
        orchestrator_discovery_ref: saga-recovery
```

这是合并到完整参与方配置中的发现片段，身份、数据源、凭据、签名及 advertised_endpoint 仍按
[业务接入指南](integration.md) 配置。纯发起方将 `saga.client.orchestrator_discovery_ref` 设置为
`saga-coordinator`，走普通业务资格；参与方的能力登记、定义同步和结果回传使用 `saga-recovery`。
`service` 是所选连接中的别名，`service_identity` 才是需要验证的逻辑协调身份。

Java、Go 等客户端可使用自己环境中的注册记录或固定受信 HTTP 入口，但仍须实现 Saga 的身份、
签名、幂等及参与方协议。注册信息不代替这些业务合同，不自动提供跨网络连通性。

## 业务资格与恢复资格

内置注册目标分别使用 `eligibility_ref: web` 和 `eligibility_ref: saga-recovery`。前者受业务就绪
约束，后者在 Saga 运行且应用未停机时允许恢复请求到达。能力租约失效后，续租不能依赖同一个
已经因租约失效而摘流的普通入口。恢复入口不授予新 Saga、timer claim 或普通 command 执行权，
请求仍要经过认证、信任期限和事务门禁。

`discovery.eligibility_probe: true` 开放 `/discovery/eligible/<注册目标名>`，例如
`/discovery/eligible/primary-http` 与 `/discovery/eligible/primary-recovery`，返回真实 200/503。
同时必须开启 `discovery.enabled`。探针只读取本地资格，不查询后端；200 不证明远端注册或
调用方网络可用。未知注册名返回 503。探针无需业务签名，应只供受信网络访问。
`/readyz` 是整个服务的业务就绪视图，`/healthz` 仅表示存活。恢复服务别名不会增加权限，也不会
使向同一 listener 发起的新 Saga 绕过就绪门禁。

内置目标默认必须在启动预算内确认注册；`startup_required: false` 才允许该目标首次不可用。
连接也有独立的 `startup_required`，默认 true；仅放宽注册目标不会同时放宽连接准备要求。
运行期默认 `readiness_critical: false`，单侧故障撤销该侧资格并上报降级，避免拖垮其他环境。
如某个目标确实是整个应用的必要依赖，可以显式设为 true。注册中心失联不代表数据库事务回滚。

短暂失联后，原记录与所有权仍有效时可恢复查询和续约。若服务端已删除记录，运行中的 owner
不会自动重新登记，因为记录丢失无法与管理端主动摘流区分。核对管理意图及远端残留后，通过
受控重启协调副本建立新 owner；不要把 Nacos 重启后的临时记录丢失等同于普通连接重试。

停机先撤销资格并摘除注册，再排空业务与 Outbox，最后关闭发现连接。注销超时或结果不明时，
应核对日志中的清理报告及远端残留；不能把进程退出解释为全部注册记录已经消失。

| 状态 | 服务行为与部署处理 |
| --- | --- |
| 必需目标首次注册失败 | 启动失败并清理已经取得的注册；检查远端残留后再启动 |
| 单侧后端失联或证据过期 | 该侧发现或注册失去资格；其它目标按各自证据继续，不跨 qualifier 回退 |
| 能力租约失效 | 普通业务可能失去就绪；恢复入口保留续租和结果回传机会，请求继续经过信任门禁 |
| 管理端删除注册记录 | 当前 owner 保守停止写入；确认管理意图后受控重启，不承诺自动重建记录 |
| 停机时注销结果不明 | 记录清理结果并检查远端，不以进程退出代替注销成功证据 |

## Kubernetes

协调器部署在 Kubernetes 时，由 Deployment/Pod、带 selector 的 Service 和控制器生成的
EndpointSlice 发布入口；应用不向 Kubernetes 自行注册。普通流量使用业务就绪探针。
恢复入口需要独立且不会被整体 `/readyz` 一并摘除的代理或后端池，并反映恢复资格和停机状态。
仅创建两个选择同一批 Pod 的 Service，仍会共享 Pod readiness，不能解决恢复通道被摘除的问题。

Kubernetes adapter 只读取 Service/EndpointSlice，不会生成 Saga 身份 metadata。Saga 客户端可
使用受信的 Service DNS 完整 URL，不能把缺少身份 metadata 的原生端点直接当成严格 Saga 逻辑
发现目标。集群外服务需要合法的集群内代理发布和双向网络路径；不支持伪造手工 EndpointSlice。

## 配置边界与观测

删除旧 `rest_discovery` 根节点后再使用 `discovery`，即使旧段 disabled 也不能同时保留。
旧的 `APP__REST_DISCOVERY__REGISTRATION__PORT` 改为内置 profile 的 `SAGA_REGISTER_PORT`；
这里的端口必须是实际可达端口，`0` 不表示自动选择。省略自定义注册项的 port 才使用 listener
端口。新模式不隐式使用 `LOCAL_NETWORK_IP`。

配置在启动时冻结。自定义注册项的 `port`、`startup_required`、`readiness_critical` 等类型
必须符合严格反序列化；连接内的数值、布尔策略也应保持正确类型。例如，额外注册项可写为：

```yaml
discovery:
  registrations:
    extra-http:
      qualifier: primary
      service_name: coordinator
      listener_ref: web
      eligibility_ref: web
      ip: 192.168.10.20
      port: 32070
      startup_required: false
      readiness_critical: false
```

此片段要求 `primary` 与 `coordinator` 已存在，且部署网络已提供不同的映射端点，不能覆盖同一
后端记录。`"32070"`、`"false"` 是字符串，不可用于上述自定义字段；任意新增字段的环境占位符
也不会自动获得数值转换。内置四个注册名的端口由加载器显式保留数值类型，账号、密码和服务名
保留字符串。需要更多注册项时，在挂载 YAML 中直接提供正确类型的值。
注册中心凭据与 Saga HMAC/签名材料是不同的信任域，应分别授权。

nafana 出口包含 `napp_discovery_*` 指标，可结合资格探针和逐注册目标状态观察失联、恢复与容量，
具体指标和判读方式见[发现状态监控](monitoring.md#发现连接与注册目标)。
后端目录健康不证明调用方网络可达，部署前仍需验证真实业务网络的路由、TLS、端口和白名单。
