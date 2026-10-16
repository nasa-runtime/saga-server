use nasa::yml::strict::{ConfigLoader, ConfigPath, LoadPolicy, ValueHint};

/// 业务作用：使用 naml 严格加载本地配置与导入文件，保留数字和布尔环境覆盖的类型。
/// 参数说明：无。
/// 返回：冻结环境与配置来源的加载器；无效路径或环境导致启动失败。
pub fn loader() -> nasa::yml::strict::Result<ConfigLoader> {
    let mut policy = LoadPolicy::default();
    for field in [
        "application.worker_threads",
        "application.startup_timeout_ms",
        "application.shutdown_timeout_ms",
        "server.port",
        "server.health",
        "server.request_body_limit_bytes",
        "server.graceful_shutdown_timeout_ms",
        "discovery.enabled",
        "discovery.eligibility_probe",
        "discovery.registrations.primary-http.port",
        "discovery.registrations.primary-recovery.port",
        "discovery.registrations.secondary-http.port",
        "discovery.registrations.secondary-recovery.port",
        "grafana.observability.enabled",
        "datasources.saga-control.max_connections",
        "datasources.saga-control.min_connections",
        "saga.orchestrator.timer_poll_interval_ms",
        "saga.api.http.expose_admin",
    ] {
        policy
            .hints
            .insert(ConfigPath::parse(field)?, ValueHint::Scalar);
    }
    Ok(ConfigLoader::standard()?.policy(policy))
}

/// 业务作用：约束独立服务只装配受管 HTTP 协调角色，流程与业务步骤由远端业务服务提供。
/// 参数说明：`app` 提供启动时已经解析的配置。
/// 返回：角色、计划、定义来源及协议匹配时成功；不匹配时拒绝开放业务入口。
pub fn validate(app: &nasa::Application) -> anyhow::Result<()> {
    // 此二进制不包含业务 handler；拒绝改变角色或定义来源，避免部署成功却无法推进业务。
    for (path, expected) in [
        ("saga.role", "orchestrator"),
        ("saga.plan_mode", "managed"),
        ("saga.definition_catalog.mode", "dynamic"),
        ("saga.transport.command_result.kind", "http"),
    ] {
        anyhow::ensure!(
            app.config_section::<String>(path)? == expected,
            "{path} must be {expected}"
        );
    }
    Ok(())
}
