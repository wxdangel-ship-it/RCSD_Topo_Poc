# T04 Step4 Candidate-Space Normalization Tasks

## P0 文档收口

- 更新 `modules/t04_divmerge_virtual_polygon/INTERFACE_CONTRACT.md`
  - 写入 `200m`
  - 写入单向扫描
  - 写入 separation stop / intrusion gate / degraded severity
- 更新 `modules/t04_divmerge_virtual_polygon/architecture/04-solution-strategy.md`
  - 删除与契约平行重复的候选空间规则
  - 只保留 normalization 设计理由
- 必要时更新 `modules/t04_divmerge_virtual_polygon/architecture/06-step34-repair-design.md`

## P1 实现对齐

- 在 `_runtime_step4_geometry_core.py` 增加 `PAIR_LOCAL_BRANCH_MAX_LENGTH_M`
- 在 `_runtime_step4_geometry_reference.py` 增加 pair-local slice 诊断 helper
- 在 `_event_interpretation_core.py`
  - 退掉双向择优主逻辑
  - 接入 200m
  - 接入 stop reason / separation metrics / intrusion gate
  - 接入 degraded severity
- 在 `variant_ranking.py` 加 severity / intrusion penalty
- 在 `case_models.py` / `outputs.py` 透传新增字段

## P2 测试增强

- 新增 `200m` 守门
- 新增单向扫描守门
- 新增 sibling continuation 合法延续守门
- 新增 separation 指标落盘守门
- 新增 separation stop reason 守门
- 新增 geometry intrusion gate 守门
- 新增 degraded `soft/hard` 分级守门
- 新增 hard degraded 可升 FAIL 守门
- 新增 accepted baseline container 语义不漂移守门

## P3 frozen real-case 回归

- 覆盖 accepted `8 case / 13 unit`
- 重点核查：
  - `760213`
  - `785671`
  - `857993`
  - `987998`
  - `17943587`
  - `30434673`
  - `73462878`
- compare 字段至少包括：
  - `boundary_branch_ids`
  - `selected_candidate_region`
  - `pair_local_middle_present`
  - `pair_local_direction`
  - `branch_separation_max_m`
  - `stop_reason`
  - `degraded_scope_reason`
  - `review_state`

## P4 最终 QA

- 审核 candidate-space 是否更贴近业务语义
- 审核 stop reason / separation 指标是否足够解释
- 审核 accepted baseline 是否无回退
- 审核是否仍保持 Step5-7 关闭

## 交付件

- `spec.md`
- `plan.md`
- `tasks.md`
- `baseline_compare.csv`
- `candidate_space_compare.csv`
- `regression_summary.json`
- `codex_report.md`
- `codex_oneclick.md`
