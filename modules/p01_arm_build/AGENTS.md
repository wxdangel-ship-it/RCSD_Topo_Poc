# P01 Arm Build 模块执行规则

## 模块边界

- 本模块只承载 `P01-A / Arm 构建`。
- 当前阶段三套数据 SWSD / RCSD / F-RCSD 独立构建 Arm，不做跨数据 Arm 配准。
- `InitialArm` 保留原始 trace 终端归并事实；当 trace 被局部边界过度切碎且 `LocalArmCandidate` 完整覆盖 InitialArm 时，`FinalArm` 可采用局部趋势兜底聚合并写明 `merge_status / merge_reason`。

## 禁止事项

- 不实现 P01-B。
- 不实现 Movement、禁行迁移或通行能力裁决。
- 不用 `grade / grade_2` 参与 Arm 构建主规则。
- 不通过几何形态反推右转专用道 / 渠化右转。
- 不静默穿越 `ambiguous_boundary`。
- 不静默丢弃 seed road。
- 不新增模块 `SKILL.md`。

## 入口边界

- 本轮不新增 repo CLI 子命令。
- 本轮不新增 `scripts/` 常驻脚本。
- 本轮不新增模块 `__main__.py` 或 `run.py`。
- 当前仅提供模块内可调用 runner，用于测试、开发验收和后续正式入口接入准备。

## 审计要求

- 输出必须包含输入路径、run id、junction group 原始 ID、trace、through decision、issue 和 review priority。
- GIS / 拓扑 / 空间数据任务必须覆盖 CRS、拓扑一致性、几何语义、审计可追溯性与性能可验证性。
