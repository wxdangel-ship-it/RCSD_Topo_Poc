# Tasks: T04 Step1-4 Runtime Detach And Baseline Guard

## Phase 1 - Specify

- [ ] T001 复核线程任务书、repo 治理入口、T04 模块 source-of-truth 与深审结论
- [ ] T002 创建 `specs/t04-step14-runtime-detach-and-baseline-guard/spec.md`
- [ ] T003 创建 `plan.md` 与 `tasks.md`
- [ ] T004 固化本轮产品边界、验收口径与 QA 裁决问题

## Phase 2 - Baseline Freeze

- [ ] T010 盘点 T04 对 T02 的 direct/transitive runtime dependency
- [ ] T011 生成 `t02_runtime_dependency_inventory.md` 的 before 部分
- [ ] T012 以当前代码运行 frozen cases，生成 before baseline 快照
- [ ] T013 记录冻结 case 的 key fields 与 review/output gate

## Phase 3 - Runtime Detach

- [ ] T020 私有化 T04 所需基础类型、normalize/helper、parser/group resolver
- [ ] T021 私有化 T04 Step1 admission contract
- [ ] T022 私有化 T04 Step2 local context runtime
- [ ] T023 私有化 T04 Step3 topology runtime
- [ ] T024 私有化 T04 Step4 legacy interpretation runtime
- [ ] T025 切换 T04 运行时代码 imports，清零 `t02_junction_anchor` runtime 依赖

## Phase 4 - No-Semantic-Change Split

- [ ] T030 拆分 `event_interpretation.py`
- [ ] T031 拆分 `rcsd_selection.py`
- [ ] T032 拆分 `tests/modules/t04_divmerge_virtual_polygon/test_step14_pipeline.py`
- [ ] T033 产出 `file_split_map.md`（如拆分面较大）

## Phase 5 - Doc Sync

- [ ] T040 同步 `INTERFACE_CONTRACT.md`
- [ ] T041 同步 `architecture/02-constraints.md`
- [ ] T042 同步 `architecture/04-solution-strategy.md`
- [ ] T043 必要时同步 `architecture/03-context-and-scope.md`

## Phase 6 - Validate

- [ ] T050 跑 T04 相关 pytest
- [ ] T051 跑拆分后新增测试文件
- [ ] T052 运行 frozen cases，生成 after baseline 快照
- [ ] T053 生成 `baseline_compare.csv`
- [ ] T054 核对 review/index/summary/case JSON/GPKG 是否稳定
- [ ] T055 回答 6 个最终裁决问题

## Phase 7 - Handoff

- [ ] T060 产出 sync handoff 目录
- [ ] T061 写 `codex_report.md`
- [ ] T062 写 `codex_oneclick.md`
- [ ] T063 写 `regression_summary.json`（如需要）
- [ ] T064 补齐 spec/plan/tasks 落盘路径说明
