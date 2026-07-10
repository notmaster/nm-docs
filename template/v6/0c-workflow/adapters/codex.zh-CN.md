# Codex adapter

Codex adapter 负责当前 CLI flag、结构化输出解析、session polling、取消和能力探测。它只接收 V6 request envelope 与隔离 workspace。原生 subagent 或 resume 是可选优化，不改变核心调度、门禁或授权。
