# T03 / Phase A Step3 repair closeout tasks

- [x] T001 收口 `INTERFACE_CONTRACT.md / spec.md / README.md / architecture/03-context-and-scope.md`
- [x] T002 统一 `input_gate_failed` 的契约归属为前置输入门禁 `reason`
- [x] T003 将 `plan.md / tasks.md` 改写为 Step3 repair closeout 口径
- [x] T004 修复 `Rule D` 的合法方向约束
- [x] T005 修复 `Rule E` 的 single-sided 前置约束与 proxy 表达
- [x] T006 修复 `Rule F` 的 cleanup_dependency 判定
- [x] T007 修复 `Rule G` 的 hard-bound-first 主通路顺序
- [x] T008 增加最终 `allowed space` 的 `DriveZone` containment 约束与 `outside_drivezone` 失败优先级
- [x] T009 补齐规则级与 run 级回归测试
- [x] T010 先定点回归 `584253 / 584141`，再决定是否真实跑 Anchor61
- [x] T011 真实跑完 Anchor61 并核对 `61` case 闭环
- [x] T012 更新现有 Draft PR 的说明，明确本轮仍只做到 `Step3`
- [x] T013 修正 `Rule A` 只截当前 branch 进入相邻语义路口的入口，且不得覆盖当前 target core
- [x] T014 修正当前 branch 双向追溯与 second-degree road 保护，并完成 `692723 / 698330` 定点回归
- [x] T015 记录 `922217 / 54265667 / 502058682` 为 input-gate hard-stop case，并从默认全量验收集排除，同时保留显式点名单复跑能力
