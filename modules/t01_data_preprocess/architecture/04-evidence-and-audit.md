# 04 证据与审计

## 1. 审计目标

T01 的运行结果必须能解释“为什么这个 road 被构成某个 Segment、为什么另一个 road 未构段、为什么某个候选被拒绝”。审计产物既服务开发排查，也服务端到端 Case 证据组织和内外网结果传递。

## 2. 运行证据

| 证据 | 业务用途 |
|---|---|
| `skill_v1_summary.json` | 全流程计数、阶段结果、诊断和性能摘要。 |
| `t01_skill_v1_progress.json` | 阶段进度和关键 trace。 |
| `t01_skill_v1_perf.json / .md / .jsonl` | 性能热点、阶段耗时和 marker。 |
| `distance_gate_scope_check.json` | 距离门控与 scope 检查。 |
| `all_stage_segment_roads/` | 各阶段 road 归属审计。 |
| `validated_pairs_skill_v1.csv` | 成立 pair 的最终证据。 |
| `segment_body_membership_skill_v1.csv` | pair-specific road body 证据。 |
| `trunk_membership_skill_v1.csv` | trunk 追溯证据。 |
| `oneway_segment_*` | 单向补段成果和统计。 |
| `unsegmented_roads.*` | 全阶段后仍未构段 road 的显式审计。 |

Step2 rejected 证据必须能解释 trunk gate 失败原因。内部语义路口转向角 gate 命中时，`support_info` 至少保留 `internal_turn_angle_node_id`、`internal_turn_angle_incoming_road_id`、`internal_turn_angle_outgoing_road_id`、`internal_turn_angle_deg`、`internal_turn_angle_threshold_deg`、`internal_turn_angle_incident_road_ids`。

## 3. 最终输出审计

Step6 输出 `segment.gpkg` 后，必须同步保留内部节点和冲突审计。内部高等级节点、`sgrade` 冲突、grade/kind 冲突不能静默修正；允许豁免的场景必须有来源字段解释，例如 Step4 高等级 terminal demotion 的来源标记。

## 4. Freeze Compare

freeze compare 的核心作用是保护 active accepted baseline。单向补段进入正式范围后，最终运行目录可以包含新增单向 Segment，但它不能被直接用于覆盖双向 baseline。更新 active freeze baseline 必须单独获得用户授权。

## 5. 文本证据包

T01 文本证据包用于内外网轻量传递。默认 compact 包只覆盖 summary、关键 CSV、hash 和审计 JSON；大体量向量 GPKG 只在显式启用 `include_vectors` 类选项时纳入。解包必须校验 payload checksum 与包内文件 checksum，并拒绝不安全路径。

## 6. 审计边界

- 对：候选、validated、rejected、trunk、segment body、单向补段、未构段 road 都有可定位证据。
- 错：只给最终 `segment.gpkg`，但无法解释构段来源、拒绝原因或冲突来源。
