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
| `t06_step1_summary.json` | Step1 运行摘要；当读取 T05 audit 时，记录 `manual_relation_anchor_override_*` 统计、释放节点和释放 Segment，用于追溯 T11 人工 relation 对 Step1 anchor gate 的影响。 |

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
| `t06_frcsd_road.* / t06_frcsd_node.*` | F-RCSD 主输出；GPKG/CSV 是稳定审计载体，逐 feature JSON 默认不写出。 |
| `t06_step3_semantic_junction_groups.*` | T05 有效关系下，物理节点分离但语义同一路口的 SWSD/RCSD node 分组与风险审计。 |
| `t06_step3_swsd_frcsd_segment_relation.*` | SWSD Segment 到 F-RCSD carrier 的稳定索引。 |
| `t06_step3_unreplaced_rcsd_roads.*` | 未进入替换结果的 RCSDRoad 基础清单。 |
| `t06_step3_unreplaced_rcsd_attribution.*` | 未替换 RCSDRoad 反向归因审计。`attribution_*` 保留 `5 > 4 > 3 > 2 > 1 > 6` 漏斗粗口径；`final_attribution_*` 先使用 replacement unit / plan 的 road-level 强证据，再按几何主 Segment 判定最终六类，避免邻近高漏斗 Segment 抢占归因。几何主 Segment 在 relation scope 内但缺少 road-level 强证据时，已在可替换范围且无 Step2/problem failure reason 的 road 回到 `5`，未进入可替换范围且 required semantic nodes / anchor 语义闭合不足的 road 回到 `3`，RCSD 方向性/承载能力不足保留 `4`。`ppt_attribution_*` 将最终六类映射到三类汇报口径：`4/5` 为 Segment下RCSD质量导致无法替换，`2/3` 为 Segment侧替换前提不满足导致无法替换，`1` 为 RCSD不在Segment范围内导致无法替换；mixed 部分覆盖不新增归因类型，仅保留低置信与人工审计标记。 |
| `t06_step3_topology_connectivity_audit.*` | final road-node integrity、source consistency、Segment 内连通和挂接质量。 |
| `t06_step3_surface_topology_audit.*` | surface-assisted closure 的贡献、阻断和风险。 |
| `t06_step3_advance_right_attachment_audit.*` | 提前右转挂接和补拓扑审计。 |
| `t06_step3_summary.json / t06_step3_detail_metrics.json / t06_step3_output_manifest.json` | 紧凑执行摘要、详细指标 sidecar 与完整输出文件清单；summary 不承载大体量列表和逐文件明细。 |

## 5. T10 Handoff

T10 visual check summary 应引用 T06 Step2 replacement plan / problem registry 与 Step3 F-RCSD / relation / topology audit，而不是只看 replaceable 数量。replacement plan 是执行边界，problem registry 是上游回流边界，topology audit 是最终 QA 边界。
