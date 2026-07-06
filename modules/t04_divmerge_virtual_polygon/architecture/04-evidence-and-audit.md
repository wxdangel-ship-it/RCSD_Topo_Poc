# 04 证据与审计

## 1. 审计目标

T04 必须能解释每个复杂候选为什么 accepted、为什么 rejected、为什么进入 review-only，以及它向 T05 交付的 relation 基点来自哪一类事实证据。弱证据和 fallback 可以存在，但必须显式标记来源和阻断原因。

## 2. 主产物证据

| 证据 | 业务用途 |
|---|---|
| `divmerge_virtual_anchor_surface.gpkg` | accepted 几何真值主成果。 |
| `divmerge_virtual_anchor_surface_rejected.*` | rejected / no-effect 结果和原因。 |
| `divmerge_virtual_anchor_surface_summary.*` | run 级统计和通过状态。 |
| `divmerge_virtual_anchor_surface_audit.gpkg` | 几何、证据、场景和约束审计。 |
| `nodes.gpkg` | downstream 状态索引，不是 T04 主几何真值。 |
| `nodes_anchor_update_audit.*` | nodes copy-on-write 更新审计。 |
| `t04_swsd_rcsd_relation_evidence.*` | 面向 T05 Phase 2 的 relation evidence。 |
| `intersection_match_t04.geojson` | T04 对 T05 发布的 SWSD-RCSD relation 候选。 |
| `step7_consistency_report.json` | 最终一致性与 cardinality 报告。 |

## 3. Full-Input 与 Case-Package 审计

case-package 用于本地复现单 case，internal full-input 用于全量批处理。两类运行都必须保留输入路径、case id、候选准入、Step4 场景、Step5 约束、Step6 几何发布和 Step7 final state。full-input 外部 T07/T03 relation 校验输入不可消费时，只按外部输入问题审计，不阻断 T04 自身构面。

## 4. Relation 审计

T04 relation evidence 必须解释 `base_id_candidate`、`required_rcsd_node_ids`、`support_rcsdroad_ids`、`surface_scenario_type` 和 `rcsd_alignment_type`。`road_surface_fork + partial` 场景中，局部 RCSD 基点可以作为下游 relation handoff base，但原语义主点必须保留为审计链，避免 T06 再反推复杂路口基点。

Step8 relation fallback 若使用 `RCSDIntersection` 作为单节点 RCSD 侧语义证据，必须在 fallback audit 中独立记录 reason：`required_rcsd_singleton_node_resolved_from_rcsdintersection`。该 reason 只表示可信 RCSDIntersection 补偿 SWSD/RCSD 几何偏差，不表示 T04 Step6 几何面成功，也不得与 `required_rcsd_singleton_node_resolved_from_strong_rcsd_profile` 合并统计。

## 5. Baseline 证据

Anchor_2 official 39-case baseline 是当前唯一正式冻结基线。历史 23/30 case 只能作为旧审计材料或子集投影，不能覆盖 official baseline 结论。
