# Plan

## 实现目标

新增 second-pass final resolver，不推翻 first-pass，只在 first-pass 输出之上做：

1. selected evidence conflict inventory
2. same-case RCSD claim 去冲突
3. cross-case conflict inventory / cleanup
4. 输出透传与 handoff compare

## 模块设计

### 1. `step4_final_conflict_resolver.py`

职责：

- 构建 same-case / cross-case evidence conflict graph
- 构建 same-case / cross-case RCSD conflict graph
- 执行 second-pass 解析与 claim 仲裁
- 回写 `T04CaseResult.event_units`
- 产出 batch 级 `second_pass_conflict_resolution.json`

### 2. first-pass 保持不动

- `event_interpretation.build_case_result()` 继续负责 first-pass candidate pool 和 case 内初选
- first-pass 不重做候选发现与 RCSD 原始召回

### 3. batch hook

- `batch_runner.run_t04_step14_batch()` 改为：
  - load/build all case_results
  - run second-pass final resolver
  - write outputs

## 关键求解顺序

### P0. inventory + freeze

- 读取 first-pass selected units
- 标记非冲突单元为 frozen
- 记录 pre-resolution candidate / claim

### P1. same-case evidence phase

- 先只建图，不默认 reopen
- 仅当 hard evidence conflict 存在时进入 evidence component
- 只有同时命中 hard RCSD conflict 时，才允许 evidence reopen
- 当前层优先；当前层无解再看下一层；仍无解则保持 baseline 并标 unresolved

### P2. same-case RCSD claim phase

- evidence 固定
- 仅在 selected aggregated support 内重选 `required_rcsd_node`
- 优先寻求 unique non-empty claim
- 如果无法在不降 support 的前提下解决，保持 baseline，不做 silent downgrade

### P3. cross-case cleanup

- 只处理 selected evidence / selected RCSD 的 batch-global component
- 当前轮默认只做 inventory 与必要 cleanup
- 无 hard cross-case component 时不改 accepted case

### P4. final consistency

- 回写新增 conflict/resolution 字段
- 同步到 `step4_event_interpretation.json`、`step4_candidates.json`、`step4_evidence_audit.json`、`step4_review_index.csv`
- 产出 `second_pass_conflict_resolution.json`

## 词典序规则

### 主证据

按以下顺序：

1. `Layer 1 > Layer 2 > Layer 3`
2. throat overlap / pair-middle overlap 更强者优先
3. `reference_distance_to_origin_m` 更小者优先
4. 与当前 selected baseline 一致者优先
5. 仍打平时保持当前选择

### RCSD claim

按以下顺序：

1. `A > B > present-only > no_support`
2. `required_rcsd_node` 可唯一化者优先
3. 与 `fact_reference_point` 更一致者优先
4. 与当前 selected baseline 一致者优先
5. same-case 内 pair-local 更局部者优先
6. 仍打平时保持当前 claim

## 输出字段

本轮新增并透传：

- `evidence_conflict_component_id`
- `rcsd_conflict_component_id`
- `evidence_conflict_type`
- `rcsd_conflict_type`
- `conflict_resolution_action`
- `pre_resolution_candidate_id`
- `post_resolution_candidate_id`
- `pre_required_rcsd_node`
- `post_required_rcsd_node`
- `resolution_reason`
- `kept_by_baseline_guard`

## 回归策略

### 自动化

- `pytest tests/modules/t04_divmerge_virtual_polygon -q -s`
- 新增 claim resolver / real-case claim freeze / output field 守门

### 基线 compare

- runtime-detach frozen set：`7 case / 12 unit`
- accepted all-A set：`8 case / 13 unit`

### 输出自洽

- `summary.json`
- `step4_review_index.csv`
- `step4_review_summary.json`
- `step4_event_interpretation.json`
- `step4_candidates.json`
- `step4_evidence_audit.json`

## 风险控制

- 不把 duplicate `required_rcsd_node` 自动升级为失败
- 不用 RCSD 冲突单独推翻主证据
- 不让 same-case tuning 扩散成 source-of-truth 重定义
- 如果 unique claim 只能靠降到 `B/C` 或清空 support，默认保持 baseline 并在 handoff 中显式保留风险
