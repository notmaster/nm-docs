# 交付恢复

使用已持久化 Operation ID 调用配置的 observe action，并在需要时调用幂等 reconcile action。重建 source commit/tree、artifact、tag/release、环境身份、已部署版本与 rollback 的完整绑定链。只有确认未开始或已安全对账的效果才能重试。Partial 或 unknown 状态需要管理员介入，或执行已获授权的回滚。
