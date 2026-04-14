# Tasks: T02 / Stage3 Anchor61 架构优化

## Phase A - SpecKit

- [x] T001 新建 `specs/t02-stage3-arch-refactor-anchor61/spec.md`
- [x] T002 新建 `clarify.md`
- [x] T003 新建 `plan.md`
- [x] T004 新建 `tasks.md`
- [x] T005 新建 `analyze.md`

## Phase B - 最小契约同步

- [x] T010 在 `INTERFACE_CONTRACT.md` 写入 Anchor61 唯一正式验收基线
- [x] T011 在 `README.md` 写入 full-input regression-only 边界
- [x] T012 在 `specs/t02-junction-anchor/spec.md` 同步基线边界说明
- [x] T013 产出 `contract_sync_diff.md`

## Phase C - 结构重构

- [x] T020 Step3 从 snapshot builder 升级为 canonical legal-space layer
- [ ] T021 Step5 统一 foreign baseline / blocking / final residue
- [ ] T022 Step6 收编 late cleanup 为 bounded optimizer
- [x] T023 Step7 去除 legacy fallback 主导权的第一阶段重构
- [ ] T024 `virtual_intersection_poc.py` 收回 orchestrator
- [x] T025 full-input regression 链只消费 canonical audit/output
- [x] T026 tri-state / visual / business outcome / summary 单轨化
- [x] T027 `kind_source` provenance 接线

## Phase D - 测试与基线对齐

- [x] T030 生成 `anchor61_manifest.json`
- [x] T031 新增 Anchor61 正式验收测试层
- [x] T032 更新测试汇报，区分正式验收层与 regression 层
- [ ] T033 若有契约冲突断言，先产出 `frozen_contract_conflict_proof.md`

## Phase E - 回归与验收

- [x] T040 跑 regression tests
- [x] T041 跑 Anchor61 正式验收
- [x] T042 产出自然执行分组统计
- [x] T043 产出目视审查结论与一致性结论
- [x] T044 产出 `audit_closure_matrix.md`

## Phase F - 总结

- [x] T050 产出 `final_refactor_summary.md`

## Round 05 当前目标

- [ ] R0501 收紧 `stage3_step7_acceptance.py`，继续剥离 legacy/fallback 主导
- [ ] R0502 收紧 `virtual_intersection_poc.py` 的 `late_*` cluster，只保留 Step6 bounded optimizer 角色
- [ ] R0503 继续收回 `virtual_intersection_poc.py` 的 monolith live truth
- [x] R0504 回归 Anchor61 与 regression，确认 Round 05 后主骨架收尾状态
- [x] R0505 产出 `final_refactor_summary.md`
