# NM V6 协议参考

[English](PROTOCOLS.md) | 简体中文

所有合同均为带版本的 JSON，并在使用前验证。未知版本、影响权限的未知字段、缺失条件字段、异常的成功结果，以及过期的 operation 或 fencing 标识都必须失败关闭。

## Agent adapter

Adapter 提供 `probe`、`start`、`poll`、`cancel` 和 `collect`。请求绑定协议版本、Operation、run、Attempt、角色、隔离 workspace、context manifest、预期结果 schema、deadline、fencing token 和允许能力。结果绑定同一 Operation 与 Attempt，并包含状态、session、candidate commit、变更路径、观察、后续请求、用量和 adapter 诊断。

Provider flag 和 session 行为只存在于对应 adapter。原生 subagent、resume 和 background task 只是可选优化。

## 项目 action

每个 action 声明非 shell `argv`、仓库相对 `cwd`、timeout、接受的退出码、环境 allowlist、核心注入名称、secret 引用、结果 schema、幂等规则；改变外部状态时还必须声明 observe 与 reconcile action。Release、publish、deploy 和 rollback 都是外部变更。Build 是 pure action，并返回 artifact digest。

核心在调用前持久化 Operation，严格按声明注入其 ID，验证 `nm-v6/action-result-v1`，再记录观察。超时、进程丢失、输出异常、`partial` 或 `unknown` 都会先触发 observe/reconcile，再允许重试。

## 受信记录

Spec confirmation、staged approval、auto grant 和 revoke 都以签名记录导入。Verifier 信任配置的公钥，而不是调用者身份字符串或终端声明。记录绑定 nonce、request digest、当前 revision、Spec/配置 hash、精确 scope、签发/过期时间、authenticator 和 signature。重放、扩大范围、过期或 revision 不匹配都会失败。

## 证据与门禁

只保留脱敏字节。状态转换时重新验证已保存字节 digest、receipt 绑定和 blob 存在性。Gate receipt 引用精确的前置 decision 与 evidence。前置门禁不表示外部效果已经发生；结果门禁会独立观察实际效果。
