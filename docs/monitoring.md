# 监控部署

`nasa` 的 `grafana` feature 引入 nafana；napp 自动注册并管理应用指标出口。Prometheus 和 Grafana 是独立容器，不进入协调器镜像，也不占有 Saga 数据库推进权限。

## 指标来源

| 地址 | 来源与内容 |
| --- | --- |
| `http://saga-server:9464/metrics` | nafana 统一 exporter：应用身份与心跳、HTTP 连接、Outbox、发现连接与注册目标、出口状态 |
| `http://saga-server:2070/_nasa/saga/metrics` | NASA Saga 聚合查询：创建、完成、补偿、人工介入、运行态、timer 与终态时延 |

两者都是 Prometheus 文本协议。第二个地址会查询数据库，抓取间隔默认 15 秒，不能使用高频抓取代替业务查询。`nasaga_lifecycle_duration_seconds` 的分位数由数据库中保留的终态事实计算，不能解释为任意 PromQL 时间窗口内的分位数。

当前依赖组合下，`nasaga_stage_duration_seconds` 的直方图来源受指标预留容量限制，不能作为可用的阶段耗时数据源；`nametrics_samples_rejected_total{reason="cardinality_limit"}` 会反映这一缺失。仪表盘的耗时面板使用持久生命周期分位数，指标拒绝面板用于提示覆盖不完整。

`up=1` 只表示本次抓取成功，不能证明 Saga Ready 或业务已完成。部署平台必须独立使用 `/readyz`；`/healthz` 用于存活检查。指标出口不决定 Saga 业务事务的提交结果。

## 动态目录与新流程接入

协调器在运行中同步持久 Catalog。`/readyz` 成功只表示整体业务资格，不保证某个新发布的流程已经激活；没有 active 定义时服务也可以 Ready。

流程拥有方使用具有对应租户和流程范围的 Registry 身份，签名调用 `GET /_nasa/saga/registry/definitions/{tenant}/{workflow}/{version}`，核对定义、摘要及生命周期。接口认证方法见[业务接入](integration.md#http-地址与认证)。默认 `validated` 策略下，候选定义需满足步骤合同、有效能力路由和目录确认后激活；使用 `approved` 时需授权管理方显式激活。

| 现象 | 应核对的事实 |
| --- | --- |
| 定义尚不存在 | 流程拥有方是否发布成功；HTTP 身份、租户、流程范围与签名公钥是否匹配 |
| 定义持续未激活 | 各步骤是否发布匹配的合同与摘要，能力租约是否有效，端点是否通过白名单，目录确认是否完成 |
| 普通业务不就绪、恢复入口仍可达 | 检查 Catalog 与能力续租；保持受信恢复通道，避免续租请求被普通业务探针阻断 |
| 创建返回 Committed 或 Duplicate | 仅表示创建事实；继续按 `saga_id` 查询业务终态 |

`watch_interval_ms` 是目录观察间隔，不是激活耗时上限。新增流程沿用既有信任配置时，定义和能力通过协议动态到达；无需编辑 YAML 或重启来触发同步。默认仪表盘不提供逐流程的定义生命周期与能力清单，不能只凭抓取成功或全局完成计数判断新流程可用。

## 发现连接与注册目标

启用 discovery 时，nafana 从受管 owner 的快照导出以下指标，抓取本身不访问注册中心。
连接标签 `connection` 对应 qualifier，注册标签 `registration` 对应 `discovery.registrations`
中的名称；这些是每个协调进程的状态，不能作为共享数据库数量去重。

| 指标 | 含义 |
| --- | --- |
| `napp_discovery_connection_prepared{connection="primary"}` | 连接初始化成功，不证明后端或业务当前可用 |
| `napp_discovery_query_errors_total` | 按连接累积的发现查询失败数，结合查询总数和观察年龄判读 |
| `napp_discovery_usable_observations` | 当前仍有可用发现证据的观察数；仅做注册的进程可以没有查询观察 |
| `napp_discovery_registration_ready{registration="primary-http"}` | 注册同时满足远端证据和本地资格时为 1 |
| `napp_discovery_registration_state` | Planned=0、Registering=1、OutcomeUnknown=2、PendingHealth=3、Active=4、Suspended=5、Withdrawing=6、Residual=7、Removed=8 |
| `napp_discovery_registration_observation_milliseconds` | 最近成功注册证据的年龄；无证据为 -1 |
| `napp_discovery_registration_readiness_critical` | 该目标故障是否影响应用整体就绪 |
| `napp_discovery_supervisor_failed` | 监督循环异常时为 1 |

资格探针 `/discovery/eligible/primary-http`、`/discovery/eligible/primary-recovery` 只反映本地
是否允许相应流量，不证明远端注册成功。普通业务资格为 503 而恢复资格为 200 时，应检查能力
租约和 Catalog，保持受信续租通道；本地资格为 200 但 registration_ready 为 0 时，检查注册
状态、后端权限、证据时效与连接情况。结合日志核对停机残留，不对处于停机中的副本发自动重建请求。

默认仪表盘与告警覆盖 Saga、Outbox 和抓取状态，未包含每个注册目标的独立面板与告警。部署方
可在现有平台增加上述序列，按副本和注册名保留维度；持续异常的阈值应覆盖后端续约与观察周期。
不要因当前没有发现查询而将 `usable_observations=0` 单独判为协调器故障。

## Grafana 仪表盘

[Compose](../docker/monitoring/compose.yml) 使用 Prometheus 和 Grafana 的独立持久卷，加载 [Prometheus 配置](../docker/monitoring/prometheus.yml)、[告警规则](../docker/monitoring/alerts.yml) 与 [Saga Server 仪表盘](../docker/monitoring/grafana/dashboards/saga-server.json)。

面板包括抓取状态、运行/补偿/等待裁决/人工介入数量、完成与补偿累计数量、到期 timer、Outbox 最旧等待、死信和端到端 P50/P95/P99。使用环境、集群、服务筛选器。Grafana 数据源 UID 为 `saga-prometheus`；导入已有平台时保持该 UID 或修改 JSON 引用。

告警由 Prometheus 求值，包括抓取失联、人工介入和持续 timer 积压。规则不自动发送通知；需要在现有平台配置 Alertmanager 或 Grafana 联系点。容量阈值应按业务规模调整。

## 多副本与聚合

不要通过随机负载均衡地址轮流采集多个进程。为每个副本配置独立 scrape target，或采用平台的 Pod/DNS 服务发现。应用实例身份在进程生命周期内稳定且副本间唯一。

共享同一 Saga 数据库的协调副本会返回同一批业务状态数量。示例使用 `max by (deployment_environment, cluster, service_name)` 去重，不能 `sum` 后当作实际实例数；Outbox 数据库聚合量也遵守此规则。一个这样的标签组合只对应一个协调数据库，不同数据库必须分配不同集群或服务身份。

进程内事件速率可跨副本求和；生命周期分位数不能相加或平均。暂时的抓取差异会使 `max` 保留一个抓取周期内的较大状态值，不能替代事务查询。Prometheus HA 场景通过平台去重查询层访问。

`saga-state` 的环境、集群、服务标签来自 Prometheus `static_configs.labels`；必须与 `grafana.observability.identity` 对齐。`saga-application` 的身份标签由 nafana 输出。Docker Compose 示例使用 `local/local/saga-server`，生产部署应同时修改两端。

## 接入现有平台

1. 将两个抓取任务合并到已有 Prometheus；更新 target、标签和路由前缀。
2. 引入示例规则；根据业务容量调整阈值并配置通知路由。
3. 在 Grafana 建立 Prometheus 数据源，UID 使用 `saga-prometheus`，导入仪表盘 JSON。
4. 确认每个 target 的 `up`、身份标签和业务状态指标；再确认平台独立监测 `/readyz`。

nafana 也提供独立 `nafana-controller` 管理平台资源，见 [nafana 统一观测合同](https://github.com/nasa-runtime/nasa-runtime-rust/blob/master/nafana/OBSERVABILITY.md)。本项目的 Compose 使用文件 provisioning，由部署方管理 Prometheus/Grafana；业务容器不持有 Grafana 管理 Token。

## 抓取安全

默认指标只依赖受信网络隔离。`9464` 不映射到宿主机，`2070` 的业务及原生 Saga 指标通过内网暴露；反向代理应阻止外部访问指标路径。Prometheus 和 Grafana 示例只绑定宿主机 `127.0.0.1`。

需要 nafana bearer 认证时，在导入配置增加：

```yaml
secrets:
  metrics-read:
    encoding: raw
    max_bytes: 512
    fragments: [{env: METRICS_READ_TOKEN}]
grafana:
  observability:
    prometheus:
      scrape:
        auth:
          mode: bearer
          token: secret://metrics-read
```

Prometheus 对应任务配置 `authorization.credentials_file` 并只读挂载同一 Token 文件。它只保护 nafana 指标出口，不能用来保护另一个 Saga 指标入口。

Grafana 官方容器用法见 [Grafana Docker 文档](https://grafana.com/docs/grafana/latest/setup-grafana/installation/docker/)，Prometheus 镜像说明见 [Prometheus 安装文档](https://prometheus.io/docs/prometheus/latest/installation/)。
