# 04 Evidence And Audit

## 1. 证据分层

T03 的证据产物分为 formal、review-only 与 internal 三层。formal 产物用于下游消费和批量验收；review-only 产物用于人工复核；internal 产物用于 full-input 运行恢复、失败定位和性能分析。三层可以互相解释，但不能互相替代。

## 2. formal 成果

batch / full-input 的正式成果必须稳定包括：

- `virtual_intersection_polygons.gpkg`：T03 accepted 虚拟路口面主成果。
- `nodes.gpkg`：downstream 状态更新，只更新当前批次 selected / effective case 的代表 node。
- `nodes_anchor_update_audit.csv`
- `nodes_anchor_update_audit.json`
- `t03_swsd_rcsd_relation_evidence.csv/json`
- `intersection_match_t03.geojson`
- `intersection_match_t03_cardinality_errors.*`：1:N / N:1 relation 冲突审计。

case 级 formal 输出继续兼容现有 `association_*`、`step6_*`、`step7_final_polygon.gpkg`、`step7_*` 文件名。这些名称是兼容契约，不代表 T03 需求主结构继续以 `Association / Finalization` 组织。

## 3. Step 级审计

`Step3` 必须留下合法活动空间冻结证据，包括 `step3_status.json`、`step3_audit.json`、`step3_allowed_space.gpkg`，以及必要的 selected road、negative mask、target edge touch 和失败原因字段。

`Step4` 必须解释 RCSD 关联语义，包括 `A / B / C`、required / support / foreign 来源、调头口判定、required core gate、降级原因和 dropped ids。

`Step5` 必须解释哪些对象进入 hard negative mask，哪些对象只是 audit-only foreign。已判定为 `related` 的 RCSDRoad 不得进入 hard mask。

`Step6` 必须解释 directional boundary、候选 polygon、几何风险和失败原因。几何 cleanup 不得静默补救拓扑或边界违反。

`Step7` 必须把结果压缩为 `accepted / rejected`；批量执行另需显式区分 `runtime_failed`。review 结论不得反写成正式机器状态。

## 4. review-only 证据

以下产物只用于人工复核，不作为正式机器状态：

- `association_review.png`
- `step7_review.png`
- `t03_review_*`
- `visual_checks/`
- `V1~V5`

review PNG 中深红 RCSDRoad 只表达强语义 `related_rcsdroad_ids / required_rcsdroad_ids`；`support_rcsdroad_ids` 保持 amber 辅助证据表达；`foreign_mask` 只能以 mask 口径表达，不得伪装成 related 线条。

## 5. internal full-input 证据

internal full-input 必须保留可恢复、可追踪的运行证据：

- `_internal/<RUN_ID>/terminal_case_records/<case_id>.json`：authoritative terminal state。
- `t03_streamed_case_results.jsonl`：compact append log，不作为唯一准真值。
- `t03_internal_full_input_manifest.json`
- `t03_internal_full_input_progress.json`
- `t03_internal_full_input_performance.json`
- early failure 可读的 progress / failure 工件。

terminal record 支撑 closeout、resume 与 retry-failed；streamed log 用于实时观测和轻量排查，不能替代 terminal record。

## 6. 下游交接证据

T03 对 T05 的交接重点是 accepted surface 与 `t03_swsd_rcsd_relation_evidence.*`。成功建议状态只允许来自 formal `step7_state=accepted` 且具备 required RCSD semantic junction 证据的 case。

T03 对 T04 的交接是 downstream `nodes.gpkg` 状态，而不是 T03 surface。T04 不应把 T03 virtual intersection polygon 当作几何输入面。

`intersection_match_t03.geojson` 是 T03 自身 relation 发布成果；项目级最终 relation 汇总与跨模块基数质检由下游统一处理。
