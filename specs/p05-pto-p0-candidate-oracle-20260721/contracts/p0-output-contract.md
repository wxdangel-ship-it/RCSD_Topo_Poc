# Contract: P05-PTO-P0 Outputs

## 1. Candidate run

不可变 candidate run 至少包含：

- `p05_pto_candidate_manifest.json`
- `p05_pto_candidate_case_index.csv`
- `p05_pto_candidate_group_index.csv`
- `p05_pto_candidates.jsonl`
- `p05_pto_candidate_lineage.csv`
- `p05_pto_candidate_summary.json`

candidate manifest 不得登记任何 truth/oracle path；`truth_input_count=0`、`truth_derived_candidate_count=0`。所有输出先完成 hash，再允许创建 label/solve run。

group index 以每个有限 optimization candidate group 作为 component，逐 Case记录 stage、mode、候选/变量/约束数和 `unbounded_enumeration=false`。P0 不自行发明业务 corridor 语义；没有正式 corridor 合同时 `corridor_id` 保持空值。

## 2. Oracle-cost solve run

不可变 solve run 至少包含：

- `p05_pto_solve_manifest.json`
- `p05_pto_oracle_costs.jsonl`
- `p05_pto_solve_certificates.jsonl`
- `p05_pto_case_index.csv`
- `p05_pto_case_metrics.json`
- `p05_pto_summary.json`
- `p05_pto_report.md`
- `cases/<sample_key>/selected_road.gpkg`
- `cases/<sample_key>/selected_node.gpkg`

solve manifest 必须固定引用 candidate manifest path/hash，并记录 label/evaluation lineage、参数、环境、资源和全部输出 hash。

## 3. Candidate schema

每个候选必须有稳定 `candidate_id`、group、stage/object kind/action、base 引用或 output payload、canonical payload hash 和至少一个非 truth 来源。内容相同的候选合并来源，不生成重复变量。

## 4. Generic constraint whitelist

- `schema_action_domain`
- `one_choice_per_base_group`
- `unique_output_id`
- `base_reference_exists`
- `endpoint_reference_exists`
- `finite_nonempty_geometry`
- `valid_generation_state`

不得加入业务归属、SPLIT 内容、方向、source、路口映射或补路规则。

## 5. Hard failure

候选缺失、truth leakage、重复 ID、缺失引用、CRS 冲突、空/非有限/零长几何、无效 action transition、非 OPTIMAL、gap 非零、materialization failure、content repair、silent fix 任一出现即对应 Gate 失败。
