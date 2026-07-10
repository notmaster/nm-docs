# Agent 与 lease 恢复

隔离旧 lease，检查独立 workspace 和 provider session，并按 Operation、Attempt、deadline 与 fencing token 验证结构化结果。拒绝迟到或异常结果。只有旧 actor 已无法改变权威状态，且不存在未对账外部效果时，才能重新派发。
