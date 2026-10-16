//! 独立 Saga 协调服务：运行中接入新流程，无需修改服务端 YAML、热加载或重启；
//! 支持数据库持久恢复与多注册中心接入。
//!
//! # 运行中接入新流程
//!
//! 已建立信任的业务服务通过受管客户端主动发布签名定义，各参与方登记步骤能力并续租。
//! 动态 Catalog 持久化定义与能力，符合激活策略后接受携带 `saga_id` 的实例创建请求。
//! `workflow` 与 `definition_version` 标识完整流程定义，`saga_id` 标识一次事务实例；
//! 已有实例冻结定义版本与摘要，新定义不会改变其步骤。
//!
//! 可信流程拥有方可在显式授权租户内使用 `workflows: ["*"]` 接入新流程名；
//! 定义归属、签名、身份及网络白名单仍须满足。新增身份、公钥或网络范围需要调整部署信任配置。
//!
//! # 协调架构与边界
//!
//! 同一协调副本可向多套 Nacos、Consul 发布普通业务和恢复入口，调用方通过具名 qualifier
//! 选择发现环境或使用受信固定 HTTP URL；注册中心不承担 Saga 状态复制、选主或租户授权。
//! 协调状态、Inbox、Outbox、timer 和 Catalog 共用数据库，租约与 fencing 约束失权推进。
//! 普通业务受就绪门禁约束，能力续租和结果回传另受恢复资格、身份及事务门禁约束。
//!
//! napp 托管初始化、注册、排空与停机；本服务只装配 HTTP 协调角色，不执行业务步骤，
//! 不提供跨服务 ACID 或物理 exactly-once。部署配置由本地挂载文件加载，变更需重启；
//! 流程定义及参与方能力通过动态 Catalog 同步，nafana 与 Saga HTTP 指标提供运行观测。

mod config;

/// 业务作用：将协调器、数据库、Outbox、HTTP 和具名注册中心的生命周期交给 napp。
/// 参数说明：`app` 是尚未开放业务入口的应用容器。
/// 返回：部署角色符合独立协调服务的边界后继续启动；配置不符时停止启动并释放受管资源。
#[nasa::application("log", "saga", "web", "discovery", config = config::loader)]
async fn main(app: nasa::Application) -> anyhow::Result<()> {
    config::validate(&app)?;
    Ok(())
}
