# 数据模型

## 1. Formal Quality Result

Segment 与 Junction 正式结果共享以下分类字段：

| 字段 | 约束 |
|---|---|
| `object_type` | `segment/junction` |
| `issue_group` | 三个固定分组之一；confirmed 必填 |
| `issue_code` | `S01-S03/J01-J04`；confirmed 必填 |
| `issue_type` | 七个正式类型之一；只对 confirmed 非空 |
| `issue_name_zh` | confirmed 必填 |
| `issue_description_zh` | confirmed 必填 |
| `result_status` | `confirmed/excluded/manual_review` |
| `root_cause_type` | confirmed 必填；来源规则或稳定失败类型 |
| `source_module` | `T12/T03/T07` |
| `source_failure_type` | 上游失败类型；无上游失败时可空 |
| `decision_rule` | 可审计决定规则 |
| `repair_domain` | confirmed 必填 |
| `repair_hint_zh` | confirmed 必填 |
| `legacy_issue_type` | 一个版本的旧值映射 |
| `silent_fix` | 恒为 false |

## 2. T07 Step2 Failure Source

内部标准行：

| 字段 | 含义 |
|---|---|
| `failure_type` | `fail1/fail2` |
| `target_id` | SWSD 代表 Junction ID |
| `related_target_ids` | 同一 fail2 冲突分量的 Junction IDs |
| `base_ids` | 相关 RCSDIntersection IDs |
| `target_group_node_ids` | SWSD 语义路口成员 IDs |
| `source_step2_root` | Step2 正式目录 |
| `source_artifacts` | nodes/error/summary/evidence 指纹 |

不保留 Step3 `error_type` 为正式业务实体。

## 3. 状态兼容映射

| `review_status` | `result_status` |
|---|---|
| `confirmed_frcsd_quality_issue` | `confirmed` |
| `excluded_false_positive` | `excluded` |
| `manual_review_required` | `manual_review` |

## 4. 旧类型迁移

| legacy | v10 |
|---|---|
| `directed_carrier_missing` | `segment_required_direction_unavailable` |
| `required_local_connectivity_missing` | `segment_required_connection_missing` |
| `unexpected_reverse_carrier` | `segment_unexpected_reverse_passability` |
| `junction_required_topology_missing` | 同名 |
| `junction_reality_or_precision_gap` | `junction_unmatched_support_topology` |

`junction_relation_cardinality_mismatch` 不做自动迁移；必须从 Step2 final state 重新生成 J03/J04。

