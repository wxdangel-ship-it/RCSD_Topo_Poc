# Contract: P05-R2 Outputs

## 1. Oracle representation run

不可变 run root 至少包含：

- `p05_r2_oracle_manifest.json`
- `p05_r2_case_index.csv`
- `p05_r2_road_edits.jsonl`
- `p05_r2_node_edits.jsonl`
- `p05_r2_t05_node_edits.jsonl`
- `p05_r2_t05_pointers.csv`
- `p05_r2_t05_node_lineage.csv`
- `p05_r2_action_coverage.json`
- `p05_r2_oracle_case_metrics.json`
- `p05_r2_oracle_summary.json`
- `p05_r2_oracle_report.md`
- `cases/<sample_key>/reconstructed_road.gpkg`
- `cases/<sample_key>/reconstructed_node.gpkg`

manifest 必须记录输入 M2R dataset/supervision manifest hash、参数、环境、耗时、输出 hash 和 `silent_fix=false`。

## 2. Edit action schema

Road action domain：`COPY/UPDATE/SPLIT/CREATE/DROP`。Node action domain：`COPY/UPDATE/CREATE/DROP`。

所有输出 payload 必须包含稳定 ID、geometry、properties、CRS 和来源。`CREATE` 不需要 base ID；其它引用 base 的动作必须指向现有基础对象。`SPLIT` 可以产生任意正数 child，不再限制为 1–3。

oracle payload 必须标记 `label_only=true`。模型推理不得读取 oracle JSONL。

T05 pointer 的候选图由同一模型本次推理生成的 T05 阶段 Node edit materialize 得到；它包含 raw Node 的 copy-on-write 结果和显式 `CREATE` Node。pointer 可以引用候选 Node 的 `id` 或非零 `mainnodeid` 语义组键。oracle 使用 `rcsdnode_out.gpkg` 只生成 label-only T05 Node edit，不得把该文件或 payload 作为输入特征。

## 3. Dataset/training/evaluation run

R2 dataset 至少输出 `p05_r2_dataset_manifest.json`、`p05_r2_dataset_index.json`、`p05_r2_dataset_schema.json`、`p05_r2_dataset_lineage.csv`、`p05_r2_input_entity_guard.csv`、`p05_r2_target_entity_guard.csv` 和 summary；内容覆盖 input/label schema、pointer candidate、edit query target、fold/entity leakage audit 和全部 hash。

Gate 2 run 至少输出 `p05_r2_gate2_manifest.json`、batch、checkpoint、curves、input-target audit、Road/Node GPKG、summary 和 report。OOF run 至少输出 manifest、五折 checkpoint lineage、逐 Case free/constrained GPKG、case index、case metrics、summary 和 report；必须记录 prediction、intervention、指标、基线、确定性和资源。

## 4. Generic constraint whitelist

- `schema_action_domain`
- `unique_output_id`
- `base_reference_exists`
- `endpoint_reference_exists`
- `finite_nonempty_geometry`
- `valid_generation_state`

约束不得选择业务归属、SPLIT 内容、方向、source、路口映射或补路。

## 5. Hard failure

以下任一出现均失败：重复 ID、缺失引用、CRS 冲突、空/非有限/零长度几何、无效 action transition、materialization failure、content repair 或 silent fix。
