# 04 证据与审计

## 1. 审计目标

T06 必须同时解释“为什么能替换”和“为什么没有替换”。替换执行、问题回流和最终 F-RCSD QA 必须分层，不能让 Step3 从诊断文件自行扩大替换范围。

## 2. Step1 证据

| 证据 | 业务用途 |
|---|---|
| `t06_swsd_segment_candidates.*` | 通过 EVD 基础检查的 SWSD Segment。 |
| `t06_swsd_segment_final_fusion_units.*` | 通过 anchor/fallback 检查的最终 Step2 输入。 |
| `t06_swsd_segment_rejected.*` | self-pair、缺 EVD、缺 anchor 等拒绝原因。 |
| `t06_step1_segment_stats.csv` | 按 `sgrade` 统计候选和 final fusion unit。 |
| `t06_step1_summary.json` | Step1 运行摘要。 |

## 3. Step2 证据

| 证据 | 业务用途 |
|---|---|
| `t06_rcsd_segment_candidates.*` | buffer 构建成功的候选。 |
| `t06_rcsd_segment_replaceable.*` | 通过全部硬审计和特殊组门控的白名单。 |
| `t06_rcsd_segment_rejected.*` | Step2 拒绝原因。 |
| `t06_rcsd_buffer_only_probe.*` | 不依赖 T05 relation 的失败诊断。 |
| `t06_rcsd_repair_candidates.*` | 可能的 pair anchor 修复候选和人工复核材料。 |
| `t06_rcsd_segment_failure_business_audit.*` | 失败业务归因和建议 owner。 |
| `t06_special_junction_group_audit.*` | 环岛 / 复杂路口组完整性审计。 |
| `t06_segment_group_replacement_audit.*` | path-corridor group replacement 准入审计。 |
| `t06_segment_replacement_plan.*` | Step3 正式执行边界。 |
| `t06_segment_replacement_problem_registry.*` | 已覆盖、已解决、需上游处理或接受不可替换的问题注册表。 |

## 4. Step3 证据

| 证据 | 业务用途 |
|---|---|
| `t06_frcsd_road.* / t06_frcsd_node.*` | F-RCSD 主输出。 |
| `t06_step3_swsd_frcsd_segment_relation.*` | SWSD Segment 到 F-RCSD carrier 的稳定索引。 |
| `t06_step3_unreplaced_rcsd_roads.*` | 未进入替换结果的 RCSDRoad 审计。 |
| `t06_step3_topology_connectivity_audit.*` | final road-node integrity、source consistency、Segment 内连通和挂接质量。 |
| `t06_step3_surface_topology_audit.*` | surface-assisted closure 的贡献、阻断和风险。 |
| `t06_step3_advance_right_attachment_audit.*` | 提前右转挂接和补拓扑审计。 |

## 5. T10 Handoff

T10 visual check summary 应引用 T06 Step2 replacement plan / problem registry 与 Step3 F-RCSD / relation / topology audit，而不是只看 replaceable 数量。replacement plan 是执行边界，problem registry 是上游回流边界，topology audit 是最终 QA 边界。
