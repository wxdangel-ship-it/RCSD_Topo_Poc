# Data Model: P05 M2R

## 1. `M2RSample`

| 字段 | 含义 |
|---|---|
| `sample_id` | 继承 M0 稳定样本 ID |
| `sample_group_id` | 业务对象/归档版本 grouped split 主键 |
| `family/business_id/scope_type` | Case 来源和人工确认粒度 |
| `fold/split` | 冻结分组 |
| `case_root/manifest_path/hash` | 输入 lineage |
| `approved_exclusion` | 是否整体关闭 |

## 2. `TaskTarget`

| 字段 | 含义 |
|---|---|
| `sample_id/task_name/target_kind` | 样本内任务目标唯一键 |
| `availability` | `available/unknown/invalid/excluded` |
| `trust_tier` | `gold/silver/pseudo/unknown` |
| `target_weight/context_weight` | loss 权重 |
| `target_selector` | 人工确认对象/Segment/Case 范围 |
| `truth_origin` | `manual_case`、`user_confirmed_strategy_replay` 或 `canonical_t10_run` |
| `strategy_replay_lineage` | 重放代码版本、输入 manifest hash、正式终态与 artifact hash；非重放标签为空 |
| `artifact_path/hash/role` | 可追溯真值 |
| `source_run/source_summary` | 产出 lineage |
| `crs` | 几何目标 CRS |
| `reason` | mask 或异常原因 |

主键：`sample_id + task_name + target_kind`。

## 3. `SharedSceneGraph`

包含候选 Road、Node、surface/raster、几何采样、属性和无标签泄漏的图边。所有数值几何在显式投影 CRS 或局部米制坐标中归一化；canonical ID 只用于引用和审计，不作为数值特征。

## 4. `TaskPrediction`

| 字段 | 含义 |
|---|---|
| `sample_id/task_name` | 预测归属 |
| `entity_key` | 节点、关系、surface 或 Road 动作对象 |
| `logits/probability/prediction` | 模型原始输出 |
| `checkpoint_hash/dataset_hash` | 复现信息 |
| `decoder_mode` | `raw/free/constrained` |

## 5. `DecoderIntervention`

| 字段 | 含义 |
|---|---|
| `sample_id/entity_key/step` | 约束触发位置 |
| `rejected_action/rejected_score` | 模型最高但非法动作 |
| `constraint_code` | 通用图约束白名单代码 |
| `selected_action/selected_score` | 次优合法动作；不存在则失败 |
| `content_repair` | 必须始终为 `false` |

## 6. `M2RRun`

不可变 run，记录输入 manifest hash、fold、配置、seed、环境、checkpoint、任务指标、逐 Case 输出、decoder audit、资源峰值和全部输出 hash。

## 7. 状态转换

```text
registered
  -> excluded
  -> target_available -> train/evaluate
  -> target_unknown   -> masked
  -> target_invalid   -> anomaly + masked

raw_prediction
  -> free_materialized | free_failed
  -> constrained_materialized | no_legal_action
```

任何 `unknown/invalid` 不得转换为 negative；任何 materialization failure 不得转换为业务 fallback。
