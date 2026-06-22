# P01 Agent Guardrails

本文件只保留 `p01_arm_build` 的 Agent 局部红线；模块源事实以 `SPEC.md`、`INTERFACE_CONTRACT.md` 与 `architecture/*` 为准。

- P01 是 Active POC / 成果模块，不替代 T09 正式契约。
- 不实现 P01-A3、P01-B、禁行迁移或通行能力最终裁决。
- 不使用 `grade / grade_2` 参与 P01 主规则。
- 不使用 RoadNextRoad `turnType / turntype` 判定 `movement_type`。
- 不通过几何形态反推右转专用道 / 渠化右转，也不只凭几何最近输出 high confidence 配准。
- 不静默穿越 `ambiguous_boundary`，不静默丢弃 seed road、RoadNextRoad、FRCSD FinalArm 或 source_extra Arm。
