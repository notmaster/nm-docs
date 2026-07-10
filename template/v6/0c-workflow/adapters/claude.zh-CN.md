# Claude Code adapter

Claude Code adapter 负责 provider 权限名、指令发现、session 行为、结构化结果解析、取消和能力探测。缺少原生 resume 或 subagent 支持时，使用新的隔离 session 回退，不改变核心语义。
