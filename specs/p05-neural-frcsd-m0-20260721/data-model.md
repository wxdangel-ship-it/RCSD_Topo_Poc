# Data Model: P05 M0

## 1. TrainingSample

| 字段 | 类型 | 含义 |
|---|---|---|
| `sample_id` | string | 来源根、业务 ID 与版本 hash 形成的稳定样本 ID。 |
| `sample_group_id` | string | `junction/case/segment` 业务组，防止重复版本泄漏。 |
| `source_family` | enum | `t03/t03_error/t04/t04_error/t10/t10_error/t10_error2`。 |
| `scope_type` | enum | `single_junction/t10_case/t10_segment`。 |
| `business_id` | string | mainnode、Case 或 Segment ID。 |
| `target_segment_id` | string/null | Segment scope 的唯一目标。 |
| `manifest_path/sha256` | path/string | 输入身份。 |
| `target_label_weight` | number | `1.0` 或 `0.7`。 |
| `context_label_weight` | number | `0.3` 或 Case 级 `0.7`。 |
| `task_mask` | list[string] | 当前确有标签的任务。 |
| `usable` | boolean | 是否至少有一个可训练任务并通过必需校验。 |
| `anomaly_codes` | list[string] | 缺失/冲突/范围问题。 |

## 2. LabelArtifact

| 字段 | 类型 | 含义 |
|---|---|---|
| `sample_id` | string | 所属样本。 |
| `label_role` | enum | `t01_segment/t07_anchor/t03/t04/t05_relation/t06_plan/t06_frcsd_road/t06_frcsd_node/t06_segment_relation`。 |
| `path/sha256` | path/string | artifact 身份。 |
| `source_run_root/repo_head` | string | canonical run lineage。 |
| `status` | enum | `available/missing/masked/invalid`。 |
| `label_weight` | number | 当前 artifact 的监督权重。 |

## 3. SplitAssignment

| 字段 | 类型 | 含义 |
|---|---|---|
| `sample_id/sample_group_id` | string | 样本与组。 |
| `fold` | int | `0..4`。 |
| `split` | enum | 默认 fold0=test、fold1=validation、其它=train。 |
| `seed/schema_version` | string | 确定性来源。 |

## 4. DataAnomaly

| 字段 | 类型 | 含义 |
|---|---|---|
| `anomaly_code` | string | 稳定错误码。 |
| `severity` | enum | `info/warning/blocking/manual_review`。 |
| `sample_id/business_id/path` | string | 定位对象。 |
| `detail` | string | 不包含猜测的事实说明。 |

## 5. RoadGraphEvaluation

| 字段 | 类型 | 含义 |
|---|---|---|
| `reference/candidate` | object | 路径、hash、CRS、feature count。 |
| `road/node metrics` | object | precision/recall/F1、匹配类型。 |
| `geometry metrics` | object | endpoint/Chamfer/Hausdorff/length。 |
| `attribute metrics` | object | direction/source/endpoint ID。 |
| `topology metrics` | object | missing endpoint、directed edge、component 与 hard fail。 |
| `failures` | list[object] | 对象级可定位失败。 |
| `silent_fix` | boolean | 固定 false。 |

## 6. ApprovedExclusion

| 字段 | 类型 | 含义 |
|---|---|---|
| `family/business_id` | string | 被用户确认排除的唯一业务对象。 |
| `reason` | string | 非空排除理由。 |
| `decision_source` | string | 用户确认来源与日期。 |

排除关闭该样本全部训练 task mask；样本、label artifact、integrity evidence 和 split assignment 均保留。

## 7. M0Run

状态：`created -> running -> passed|blocked|failed`。输出根已存在、范围越界、CRS 阻断、lineage 错批次或成功标准未满足时不得标记 `passed`。
