# 013 Step2 多候选锚定正式方向消歧重试

- 时间：2026-06-13
- 模块：T06 Segment Fusion Precheck / Step2
- 变更类型：单向 Segment 的多候选 pair anchor 受限自动消歧

## 根因

T10 991176 审计发现，部分高等级单向 SWSD Segment 在 T05 relation 层呈现 `multi_anchor_ambiguous`：SWSD 语义路口与 RCSD 语义路口不是稳定 1V1，buffer-only probe 可以在 50m core 内找到高重合、方向和连通均满分的 RCSD corridor，但 Step2 原 relation mapping 失败后只输出人工候选，没有把候选 pair 的 as-is / reversed 方向带入正式 extractor 复核。

典型现象是候选 pair 的原始顺序不满足 RCSD 单向有向 path，而 reversed 顺序通过正式 `BufferSegmentExtractor` 与既有 graph-first 硬审计。此前该类 Segment 被保留为 rejected，导致本应可替换的 RCSD Road 未进入 Step3。

## 业务逻辑变更

Step2 对 relation mapping 失败后的 `multi_anchor_ambiguous` 新增受限 formal retry：

1. 仅对 `directionality=single` 生效。
2. 仅接受 `source_reject_reason in {invalid_pair_relation_status, invalid_pair_base_id, missing_pair_relation}`。
3. `BufferOnlyProbeResult.status` 必须为 `ambiguous_corridor`。
4. 候选评分必须满足：`candidate_score >= 0.95`、`geometry_overlap_ratio >= 0.85`、`directionality_score = 1.0`、`connectivity_score = 1.0`、`shape_similarity_score >= 0.95`。
5. 对 probe 输出的全部 `candidate_pair_sets` 逐个试算 as-is 与 reversed 两个方向。
6. 单向多候选消歧必须检查 oriented RCSD pair 与 SWSD Segment 轴向端点侧位一致：若某候选把 SWSD 起点侧映射到靠近 SWSD 终点侧的 RCSD node，或反之，则不得参与唯一通过判定。
7. 每个方向都必须重新经过正式 `BufferSegmentExtractor`；若正式 extractor 失败，仅允许沿用既有 `SingleGraphConnectivityRetry` 的 graph-first 50m core、长度比、端部外延与几何覆盖门槛。
8. 只有恰好一个 oriented candidate 通过全部正式硬审计时，才把该 Segment 输出为 replaceable。
9. 多个 oriented candidate 通过、没有候选通过、或任一必要上下文无法判定时，仍保持 rejected / 人工复核。

本变更不回写 T05 relation，不修改输入字段语义，不新增属性推断，不扩大整体 buffer。

## 拆分与职责边界

- `pair_anchor_formal_retry.py` 承接候选 pair 的 as-is / reversed 正式试算与唯一 outcome 判定。
- `pair_anchor_relation_retry.py` 新增 relation mapping 失败分支与 buffer extraction 失败分支的 formal retry 编排，统一调用正式试算、junc audit 与输出行 helper。
- `pair_anchor_formal_retry_rows.py` 继续只负责已通过 outcome 的 `buffer_only_probe / repair_candidates / candidates / replaceable / failure_business_audit` 落表。
- `step2_extract_rcsd_segments.py` 只保留主流程调用和统计累加，避免 Step2 主文件回填重试细节。

## GIS / 拓扑检查

- CRS 与坐标变换：不新增 CRS 处理，继续复用 T06 Step2 已归一化的 EPSG:3857 几何。
- 拓扑一致性：不 silent fix；候选 pair 方向必须重新通过正式 directed path / graph-first 受限硬审计。
- 几何语义可解释性：仍以 SWSD Segment 的 50m core buffer 作为核心约束；graph-first 只允许在经过 50m core 的前提下进行纵向补足；multi-anchor 消歧额外要求 oriented RCSD pair 在 SWSD Segment 轴向上的起终侧位一致。
- 审计可追溯性：输出记录原始 relation、候选 pair、source reject reason、failure business category、adaptive source reason 与最终 retained RCSD road/node。
- 性能可验证性：仅命中高置信 `multi_anchor_ambiguous` 的单向 Segment 才遍历全部候选 pair，每个 pair 最多两个方向；未命中场景不增加正式试算。

## 回归

- 新增 `test_multi_anchor_formal_retry_accepts_unique_reversed_candidate`：候选 pair as-is 失败、reversed 唯一通过时输出 replaceable outcome。
- 新增 `test_multi_anchor_formal_retry_rejects_multiple_valid_candidates`：多个 oriented candidate 通过时保持 rejected。
- 新增 `test_multi_anchor_formal_retry_filters_orientation_with_reversed_endpoint_side`：多个候选能通过正式 extractor 时，端点侧位反向的 oriented candidate 不参与唯一通过判定。
- 新增 `test_multi_anchor_formal_retry_requires_explicit_enablement`：未显式开启 multi-anchor 分支时不改变原 formal retry 行为。
