# CLI Contract: T12 FRCSD 质量审计

## 1. Standalone 正式入口

```bash
.venv/bin/python scripts/t12_run_frcsd_quality_audit.py \
  --swsd-segment <segment.gpkg> \
  --swsd-roads <roads.gpkg> \
  --swsd-nodes <nodes.gpkg> \
  --frcsd-roads <original_1v1_frcsd_road.gpkg> \
  --frcsd-nodes <original_1v1_frcsd_node.gpkg> \
  --t05-anchor-audit <intersection_match_all_audit.csv> \
  --rcsd-intersection <RCSDIntersection.gpkg> \
  --t06-run-root <t06_run_root> \
  --out-root <output_root> \
  [--run-id <run_id>] \
  [--drivezone <DriveZone.gpkg>] \
  [--case-manifest <t10_case_evidence_manifest.json>] \
  [--review-decisions <review.csv>] \
  [--progress]
```

## 2. 必选参数

- `--swsd-segment/roads/nodes`：同一 T01/最终 SWSD handoff 的 Segment、Road、Node。
- `--frcsd-roads/nodes`：原始 1V1 FRCSD，被检 target；不得传 T06 Step3 输出。
- `--t05-anchor-audit`：T05 成功/失败 relation、source module 和 grouped node 证据。
- `--rcsd-intersection`：T07 人工标准路口输入，用于 truth-anchor 身份审计。
- `--t06-run-root`：由当前 1V1 FRCSD 经同批次 T05 copy-on-write 后作为 compatibility carrier 得到的 T06 证据根；T12 校验 T05/T06 派生链，不要求 T06 输入与原始 target 指纹相同。
- `--out-root`：输出父目录；实际写入 `<out-root>/<run-id>/`，该运行根必须尚不存在，否则在加载输入前阻断。

## 3. 可选参数与默认值

- `--run-id`：默认 `t12_frcsd_quality_audit_<UTC timestamp>`。
- `--drivezone`：几何参考证据；缺失时相应字段为 `not_provided`，不得替代拓扑结论。
- `--case-manifest`：Case manifest；提供 Case bounds 以执行 500 m crop-edge 审计。全量运行可不传。
- `--review-decisions`：复核决定；缺失时所有自动候选进入 `manual_review_required`，最终确认数为 0。
- `--local-corridor-m`：默认 `50.0`。
- `--portal-radius-m`：默认等于 `local-corridor-m`，不得小于它。
- `--path-max-length-ratio`：默认 `1.5`。
- `--path-max-additive-m`：默认 `100.0`。
- `--path-max-corridor-distance-m`：默认 `50.0`。
- `--sample-spacing-m`：默认 `5.0`。

## 4. 退出码

| 退出码 | 含义 |
|---:|---|
| `0` | 运行通过；可包含待复核候选或已确认问题。 |
| `2` | 输入、CRS、target identity、输出覆盖风险、参数或复核合同阻断。 |
| `1` | 非预期运行失败；必须留下 failure audit。 |

质量问题数量不决定进程失败；T12 是 audit-only。

## 5. T10 调用

T10 Case/full stage 使用同一 callable/参数语义，并以显式 `frcsd_1v1_roads / frcsd_1v1_nodes` slots 传入 target。`RUN_T12=0` 时保持既有 stage；`RUN_T12=1` 时缺失任何必选输入必须阻断 T12 stage，不得回退借用 `RCSDROAD_PATH/RCSDNODE_PATH`。
