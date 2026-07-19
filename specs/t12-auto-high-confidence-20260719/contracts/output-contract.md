# Output Contract：自动高置信决定

## 1. 正式问题

`t12_frcsd_confirmed_quality_issues.csv/.gpkg` 只包含自动高置信确认或显式外部 override 确认的记录。无 review 输入时该文件仍可非空。

## 2. 候选决定

每个候选必须且只能归入 confirmed、excluded 或 explicit-manual-override 之一。默认自动运行不产生 manual。

新增或正式启用字段：

| 字段 | 值域 / 含义 |
|---|---|
| `decision_source` | `automatic_high_confidence` 或 `external_review_override`。 |
| `decision_rule` | `raw_carrier_missing_trusted_anchor`、`equivalent_raw_carrier`、`insufficient_anchor_confidence` 或外部覆盖标识。 |
| `anchor_confidence` | `t07_standard_surface`、`t03_pair` 或 `insufficient`。 |
| `raw_local_directed_status` | 每个必需方向的 raw endpoint directed path 状态。 |
| `raw_local_undirected_status` | 每个必需方向的 raw endpoint undirected path 状态。 |
| `raw_full_directed_status` | 每个必需方向的 raw endpoint full directed path 状态。 |
| `semantic_local_directed_status` | 同 portal 策略下 canonical local directed 对比状态，只用于问题类型解释。 |
| `semantic_local_undirected_status` | 同 portal 策略下 canonical local undirected 对比状态，只用于问题类型解释。 |

既有 `review_status/review_reason/review_source/reviewed_at_utc` 为兼容字段：自动决定也填充相应状态和原因；外部 override 时填充外部来源和时间。

## 3. 计数

summary 至少包含：

- `candidate_count`
- `confirmed_quality_issue_count`
- `review_exclusion_count`
- `manual_review_required_count`
- `by_issue_type`
- `by_review_status`
- `by_decision_source`
- `by_decision_rule`
- T07 surface 关联 pass/missing/ambiguous 统计

passed 运行必须满足：

```text
candidate_count = confirmed_quality_issue_count
                + review_exclusion_count
                + manual_review_required_count
```

## 4. 空间证据

carrier evidence 必须保留 raw graph 的 Road ID、raw start/end node、方向、路径长度、长度比、最大走廊偏离和 portal 来源。canonical 路径只作候选/对比证据，不得覆盖 raw verdict。

## 5. 安全

- 不覆盖已存在 run root。
- 不修改任何输入。
- `silent_fix=false`。
- 输出保持 processing CRS，并记录所有显式转换。
