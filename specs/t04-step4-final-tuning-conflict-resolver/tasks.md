# Tasks

## P0 基线冻结与冲突 inventory

- [ ] 收集 runtime-detach frozen `7 case / 12 unit`
- [ ] 收集 accepted all-A `8 case / 13 unit`
- [ ] 建 same-case evidence conflict inventory
- [ ] 建 same-case RCSD claim inventory
- [ ] 建 cross-case conflict inventory
- [ ] 标记 non-conflict frozen units

## P1 same-case 主证据冲突仲裁

- [ ] 新增 evidence conflict primitives
- [ ] 建 same-case evidence connected components
- [ ] 仅对 hard evidence component 开启 resolver
- [ ] 只在 dual conflict 时允许 evidence reopen
- [ ] 输出 evidence component id / type / action

## P2 same-case 正向 RCSD claim 仲裁

- [ ] 新增 same-case RCSD claim component 求解
- [ ] 从 selected aggregated support 内生成 claim 备选
- [ ] 优先 unique non-empty claim
- [ ] 保持 `A/primary_support` 不回退
- [ ] 重点验证 `17943587`

## P3 cross-case 冲突清理

- [ ] 建 cross-case evidence / claim graph
- [ ] 对 hard component 做 cleanup
- [ ] 无 hard component 时只落 inventory

## P4 联合一致性检查 + 输出透传

- [ ] 回写 event unit 新字段
- [ ] 更新 `step4_event_interpretation.json`
- [ ] 更新 `step4_candidates.json`
- [ ] 更新 `step4_evidence_audit.json`
- [ ] 更新 `step4_review_index.csv`
- [ ] 新增 `second_pass_conflict_resolution.json`

## P5 回归与 QA

- [ ] 增加 resolver 单测 / real-case claim freeze / batch compare 守门
- [ ] 跑 `pytest tests/modules/t04_divmerge_virtual_polygon -q -s`
- [ ] 生成 `baseline_compare.csv`
- [ ] 生成 `conflict_inventory.csv`
- [ ] 生成 `conflict_resolution_summary.csv`
- [ ] 生成 `regression_summary.json`
- [ ] 输出 handoff `codex_report.md` / `codex_oneclick.md`
