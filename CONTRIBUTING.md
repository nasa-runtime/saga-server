# 参与开发

服务装配使用 NASA 的公开能力，协调状态机、投递协议和持久结构保持在对应组件中。配置或接口变更需同步维护中英文使用说明、Docker 配置和监控定义。

公开使用入口包括中英文 README、crate 文档、Cargo description/keywords/categories、镜像描述、
`docs` 中的接入/发现/监控指南、`SECURITY.md`、`zcf` 配置及 `examples` 部署样例。多注册中心
相关说明须一致描述 qualifier 选择、业务与恢复资格、映射端点、身份信任和失败后果。

动态流程说明须区分定义身份、步骤能力与事务实例 ID：已授权业务通过协议接入新流程，协调服务持续运行；部署信任配置与动态目录分别管理。对外说明应保留不可变定义、既有实例冻结、激活前置条件和通配流程权限的边界。

使用 Rust 1.94 或更高版本和 crates.io 的 `nasa 2.0.3`，保留 `Cargo.lock` 并执行：

```sh
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
cargo build --locked --bin saga-server
bash docker/build-image.sh
```

Docker 相关脚本和部署文件统一位于 `docker/`，工作流在 `.github/workflows/` 调用这些入口。
维护分支使用 `master`，发布分支固定为 `release`；Git 版本标签与 manifest 软件版本一致，例如 `1.0.0`。镜像构建、仓库参数与上传约束见[镜像发布说明](docker/README.md#源码构建与镜像发布)。

镜像脚本使用服务目录中的源码和锁文件，构建环境须能取得对应的 registry 依赖；`SAGA_IMAGE` 可覆盖镜像标签。

项目使用 MIT OR Apache-2.0 双许可证。提交内容不得包含业务凭据、私钥、数据库数据或编辑器个人配置。
