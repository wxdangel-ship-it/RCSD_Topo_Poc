# Contract: P05 M2R Outputs

## 1. Supervision run

不可变目录至少包含：

- `p05_m2r_supervision_manifest.json`
- `p05_m2r_task_targets.csv`
- `p05_m2r_task_coverage.json`
- `p05_m2r_label_anomalies.csv`
- `p05_m2r_split_audit.json`
- `p05_m2r_supervision_report.md`

`task_targets.csv` 每行必须包含 `sample_id,sample_group_id,family,business_id,fold,split,task_name,target_kind,availability,trust_tier,target_weight,context_weight,target_selector,artifact_role,artifact_path,artifact_sha256,crs,source_run,reason`。

## 2. Dataset run

- `p05_m2r_dataset_manifest.json`
- `p05_m2r_scene_index.csv`
- `p05_m2r_task_index.csv`
- `p05_m2r_feature_schema.json`
- `p05_m2r_leakage_audit.json`
- 分 fold tensor/array 工件及 hash

manifest 必须证明 excluded 样本数、Unknown mask、train-only normalization 和跨 fold 零泄漏。

## 3. Training run

- `p05_m2r_training_manifest.json`
- `p05_m2r_model_config.json`
- `p05_m2r_checkpoint.pt`
- `p05_m2r_training_history.json`
- `p05_m2r_task_metrics.json`
- `p05_m2r_resource_metrics.json`

任务指标必须包含分母、mask 后样本数、类别分布、loss、small-batch overfit 和验证指标。

## 4. OOF evaluation run

- `p05_m2r_oof_manifest.json`
- `p05_m2r_case_metrics.json`
- `p05_m2r_task_metrics.json`
- `p05_m2r_decoder_interventions.csv`
- `p05_m2r_evaluation_summary.json`
- `p05_m2r_evaluation_report.md`
- `cases/<decoder_mode>/<sample_id>/road.gpkg`
- `cases/<decoder_mode>/<sample_id>/node.gpkg`
- `cases/<decoder_mode>/<sample_id>/metrics.json`

## 5. 通用约束白名单

允许的 `constraint_code`：

- `schema_action_domain`
- `unique_output_id`
- `endpoint_reference_exists`
- `finite_nonempty_geometry`
- `valid_split_order`
- `generation_state_transition`

任何新增约束必须先更新本合同并证明不编码 Segment 归属、SPLIT、方向、路口映射或补路业务判断。

## 6. Hard failure

以下任一出现都必须计失败：CRS 冲突、重复 ID、缺失引用、非有限/空/零长度几何、无合法动作、materialization failure、事后内容修复、silent fix。
