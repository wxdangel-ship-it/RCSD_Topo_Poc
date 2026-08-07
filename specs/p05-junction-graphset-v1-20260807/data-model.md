# 数据模型

## CityEvidenceStore

城市级只读对象仓，记录输入 manifest/hash、CRS、SWSD/RCSD/DriveZone/
RCSDIntersection/道路面/导流带对象索引、几何 token 分片和拓扑边。原始 GIS 每次运行
只解析一次；训练和推理通过对象 ID 引用，不复制城市对象。

## JunctionQuery

- `case_key`
- `semantic_junction_id`
- `swsd_object_ids`
- `dynamic_dependency_object_ids`
- `role_spans`
- `allowed_stage_masks`

空间查询窗口不是业务边界；依赖对象由拓扑与正式关联闭包决定。

## JunctionEvidenceBatch

- `swsd_geometry_tokens: [Ns, 21]`
- `drivezone_geometry_tokens: [Nd, 21]`
- `rcsd_intersection_tokens: [Ni, 21]`
- `rcsd_node_tokens: [Nn, 21]`
- `rcsd_road_tokens: [Nr, 21]`
- `divstrip_tokens: [Nv, 21]`
- `topology_edges: [E, 8]`
- `object_spans`
- `candidate_plan_index`
- `stage_visibility_masks`

标签、Case family、规则终态和 evaluator 结果不得存入该 batch。

## JunctionResultPrediction

- `junction_key`
- `step1_drivezone_state`
- `surface_plan`
  - `mode`
  - `selected_rcsdintersection_ids`
  - `virtual_surface_logits/geometry_recipe`
- `anchor_result`
  - `state`
  - `associated_rcsd_node_ids`
  - `associated_rcsd_road_ids`
  - `selected_main_anchor`
  - `node_equivalence_classes`
  - `road_break_operations`
- `post_materialization_topology_signature`
- `quality_state/review_reason`
- `component_confidences`
- `complete_plan_confidence`
- `abstain`

## JunctionLabelOverlay

按字段保存 label value、task mask、source weight、acceptable set、UNKNOWN/Review 和来源
证据引用。它与 `JunctionEvidenceBatch` 物理分离，只在 loss/evaluator 连接。

## VirtualSurfaceConstraint

每个可见 RCSD Node/Road 的状态为 `REQUIRED / FORBIDDEN / UNKNOWN`。冲突记录进入
Review，权重为 0；几何形状只作为生成/物化辅助，不作为旧规则 polygon exact 真值。

## MaterializationLedger

保存模型方案、执行的几何操作、最终对象、拓扑校验、fallback 作用域、输入/模型/
materializer hash 和失败原因。确定性层不得在 ledger 中产生新的业务选择。
