# T09 Step3 retained SWSD seed carrier fallback 履历

## 2026-06-11

### 背景

T10 `609214532` 与 `1885118` 复测中，T09 Step3 仍存在少量 `from_arm_approach_missing / to_arm_exit_missing`。抽查发现部分 T09 Arm 的 seed road 没有进入 T01 Segment，因此没有出现在 T06 `t06_step3_swsd_frcsd_segment_relation` 中；但这些 road 并未被 T06 替换删除，仍以 `source=2` 存在于 T06 F-RCSD Road 输出。

### 根因

T09 Step3 只从 T06 Segment relation 的 `frcsd_road_ids` 建立 Arm carrier。对未进入 Segment relation、但仍保留在 F-RCSD 中的 SWSD seed road，Step3 无法识别 approach / exit carrier，导致已由显式 restriction 还原的 SWSD Movement 无法投影到 F-RCSD restriction。

### 业务逻辑变更

- 增加 `retained_swsd_seed_fallback` carrier 路径：仅当 T09 Arm seed road 同 ID 出现在 T06 F-RCSD Road 输出，且 `source=2`，并且 road endpoint direction 能在 SWSD junction alias 上解释为 approach / exit 时才使用。
- fallback 不创建 road，不修改 T06 输出，不反推字段语义；它只消费 T06 已明确保留的 SWSD Road。
- 使用 fallback 的 Arm 输出 `retained_swsd_seed_carrier_fallback` 风险标记，供后续质量分析识别。

### 验证记录

- 新增单测覆盖未进入 Segment relation 的保留 SWSD seed road 可参与 F-RCSD restriction 投影。
- 后续 T10 复测需重点观察 `from_arm_approach_missing / to_arm_exit_missing` 是否下降，以及是否只新增 `source=2` 保留 carrier 的 restriction。

