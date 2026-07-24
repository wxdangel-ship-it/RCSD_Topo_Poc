# P05-JSG-PTO-P0 输出合同

每个不可变 run 至少输出：

```text
run_manifest.json
run_summary.json
case_inventory.csv
object_coverage.json
review_inventory.csv
anomalies.csv
cases/<case_key>/
  jsg_truth.json
  jsg_evaluation.json
  compiler_manifest.json
  compiled_road.gpkg
  compiled_node.gpkg
  roadgraph_evaluation.json
  artifact_manifest.json
```

## 必备断言

- `schema_version` 与 `run_id` 固定。
- 输入只位于允许的 `E:\TestData\POC_Data` 根或引用已冻结 P05 `outputs/_work` Oracle 证据。
- 每个外部输入、JSG truth、编译输出和报告均记录 SHA-256。
- `label_only=true`、`content_repair=false`、`silent_fix=false`。
- Case failure 进入 run summary 并保留局部证据，不删除或缩小分母。
- 第二轮 run 不覆盖第一轮，确定性通过 canonical signature 比较。

## 状态口径

- `PASS`：全部 hard gate 通过。
- `REVIEW`：业务证据冲突或不足，但本体能无损表达且未自动决策。
- `FAIL`：schema、引用、CRS、编译、RoadGraph 或 lineage hard gate 失败。

`REVIEW` 不是 `FAIL`，但必须计数、定位和保留证据。
