# P05-Scheme-A-Dataset-P1 验证摘要

## 决策

`P05_SCHEME_A_DATASET_P1_GO`

本结论只放行新的 Segment-scoped 标签合同；不授权训练、调阈值、在线 proposal、
生产接入、T01–T12 修改、Movement 处理或 Git 操作。

## 正式证据

- Run A：`p05_scheme_a_dataset_p1_20260723_01`
- Run B：`p05_scheme_a_dataset_p1_20260723_02`
- signature：
  `bc848a8a0eeda04c14b358d505bc70258deaf36bb40cb617611ba7c4d205065c`
- Run B `reference_run_match=true`
- `segment_package_lineage.jsonl`、`segment_label_scope.jsonl`、
  `expected_failure_scope.jsonl`、`historical_metric_invalidation.jsonl`
  的 Run A/B SHA-256 分别完全一致。

## 标签与 lineage

- 输入：741 sample、51 Case、8,863 当前 T01 Segment。
- 启用 Segment 包：45；批准排除进入标签：0。
- direct ID：41，其中 Road drift 5；Road drift 只记录旧包与当前 T01 的 Road
  清单变化，不改变同 ID 业务身份。
- ID 已消失的一对多 lineage：4 个包，分别映射 3/4/7/13 个当前 Segment；
  冻结目标 Road 集合均被无遗漏、无重复、无额外 Road 地精确分区。
- 标签：6,275，其中 T10 Case truth 6,207、Segment 包 target/descendant 68。
- 纯上下文：2,588；`label_eligible=false`、`label_weight=null`、
  `context_input_weight=0.3`，label/loss/metric leakage=0。

## expected failure

- Case 终态保持 49 `LEGAL` + 2 `EXPECTED_FAIL`。
- `T10:609214532`：每 seed 1,795 个历史级联 mask，修正后只定位
  `advance_right_a675eda6ba1c4aba` 一个失败 group。
- `T10:74155468`：每 seed 159 个历史级联 mask，修正后只定位
  `advance_right_123cb24480306815` 一个失败 group。
- 历史级联 mask 合计 5,862 个 seed-object 行；新合同级联 mask=0。
- Case 仍禁止发布并输出 RealityChangeClue；其它 Segment scorer 资格不再被 Case
  终态覆盖。

## GIS、确定性与资源

- CRS：唯一 `EPSG:3857`，无坐标变换。
- geometry read/write=0；只读取冻结 skeleton 的 ID、Road 归属和审计字段。
- skeleton mutation=0，content repair=false，silent fix=false。
- Run B wall=`4.965s`，peak RSS=`362,168,320` bytes，GPU VRAM=0。
- 新代码专项测试：6 passed；完整 P05 回归：205 passed。
- 未训练模型、未处理 Movement、未修改 T01–T12、未新增入口。

## 历史结论重解释

Scheme A baseline、Dataset-P0、P1、P2-P0/P1、P2-P2 系列和 P2-P3-P0/P1
原始工件全部保留。冻结骨架、candidate inventory、通用图合法性、49+2 安全等
不依赖旧标签分母的事实继续有效；以 8,863 为标签分母的训练、错误率、coverage、
recall、macro-F1、stable-wrong 和 fold 2 coverage-ceiling 结论必须在 Dataset-P1
上重新训练或重新评价后才能使用。
