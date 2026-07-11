# Tasks: T10 六用例无损性能优化与 60 KB 架构收敛

## Phase 1 - Setup & source facts

- [x] T001 核验主仓库 `main`、remote、HEAD、dirty state 和现有 worktree。
- [x] T002 核验三个正式 T10 基线指针及 Windows/WSL 路径映射。
- [x] T003 创建 `codex/t10-performance-60pct-20260710` 临时工作树与分支。
- [x] T004 读取 repo `README.md`、项目级源事实、T10 源事实、体量/入口治理文档和 `default-imp`。
- [x] T005 计算正式六用例阶段耗时、Case 耗时和 `1991.604s` 目标。
- [x] T006 完成 693 个 tracked 受治理文件的实时体量审计，登记 55 个超 60 KB 文件。
- [x] T007 创建 `spec.md / research.md / plan.md / tasks.md`。
- [x] T008 完成 `analyze.md`，检查任务、源事实、入口、契约、体量和验证覆盖的一致性。

## Phase 2 - Reference & profiling foundation

- [x] T010 验证工作树 `.venv`、WSL、Python 3.10、六用例 package 和独立 `_work` 输出根。
- [x] T011 [US2] 建立正式业务产物比较清单与允许忽略字段清单。
- [x] T012 [US2] 先写业务指纹/结构化等价比较测试或 test helper，不新增正式入口。
- [x] T013 [US1] 运行当前 main 未优化 `1885118` reference，保存 stage status、业务指纹和 wall-clock。
- [x] T014 [US1] 运行当前 main 未优化六用例 reference，登记相对 `96b0ea5` 的既有业务差异。
- [x] T015 [US1] 对 `1885118` T03/T04/T06 Step3 采集动态 profile、I/O、CPU、内存和调用热点。
- [x] T016 [US1] 形成按收益/风险排序的优化候选清单；每项写明业务等价理由和验证方法。

## Phase 3 - T03 hotspot and 60 KB convergence

- [x] T020 阅读 T03 `AGENTS/SPEC/architecture/INTERFACE_CONTRACT` 与相关 tests。
- [x] T021 [US2] 为 T03 输出并发与 closeout 复用建立 characterization/import tests；三个超线算法文件的拆分 characterization 随 T022 同步补齐。
- [x] T022 [US3] 写前置 bytes 记录并拆分 T03 三个超 60 KB 文件，保留 public surface；拆分后最大文件 `47907 bytes`，T03 模块 `234 passed`。
- [x] T023 [US1] 基于 profile 完成首批 T03 独立输出并发与 closeout geometry 复用，不改变候选/输出。
- [x] T024 [US2] 运行 T03 单元/契约测试与结构化结果比较。
- [x] T025 [US4] 运行 `1885118` 至 T03/完整链路门禁，确认业务差异为 0并记录耗时。

## Phase 4 - T04 hotspot and 60 KB convergence

- [x] T030 阅读 T04 `AGENTS/SPEC/architecture/INTERFACE_CONTRACT` 与相关 tests。
- [x] T031 [US2] 为 T04 `_event_interpretation_core.py / step4_road_surface_fork_binding_promotions.py / final_publish.py` 和超线测试建立 characterization coverage。
- [x] T032 [US3] 写前置 bytes 记录并拆分 T04 超 60 KB 文件，保留原 callable/import。
- [x] T033 [US1] 基于 profile 优化 T04 重复空间计算、candidate materialization 或输出准备。
- [x] T034 [US2] 运行 T04 单元/契约测试与结构化结果比较。
- [x] T035 [US4] 运行 `1885118` 至 T04 门禁，业务工件等价，wall-clock `170.37s -> 138.09s`。

## Phase 5 - T06 hotspot and 60 KB convergence

- [x] T040 阅读 T06 `AGENTS/SPEC/architecture/INTERFACE_CONTRACT` 与相关 tests。
- [x] T041 [US2] 为 T06 research 清单中的全部超 60 KB source/test 文件建立 characterization/import coverage。
- [x] T042 [US3] 写前置 bytes 记录并拆分 T06 Step2/Step3/replacement/topology/text-bundle/attribution 超线文件。
  - 已完成 `step3_segment_replacement.py`：`102059 -> 546 bytes` facade；runner/support/primitives/models 最大 `42673 bytes`，入口兼容且均低于 60KB。
- [x] T043 [US1] 基于 profile 优化 T06 Step3 重复 graph/geometry/index/output 准备；保留向量化 coverage cache，Fiona/GPKG 并发写出因实测回退已关闭。
- [x] T044 [US2] 运行 T06 单元/契约测试、T06 正式审计和结构化结果比较；T06 模块 `382 passed`，1885118 Step3 42 工件业务差异为 0。
- [x] T045 [US4] 使用基线相同 WSL `.venv` 运行 `1885118` T06 Step1/2 + Step3 门禁；所有 GPKG/CSV 业务工件等价，Step3 关键计数一致，完整 T06 测试 `382 passed`。
- [x] T046 [US1] Phase 3-5 六用例回归 `t10_phase35_v2_6cases_20260711`：6/6 passed，36,731 个结构化工件业务等价；九阶段合计 `2993.610s`，相对 current-main `3668.089s` 下降 `18.39%`，距正式目标仍差 `1002.007s`。

## Phase 6 - Remaining T10-chain 60 KB convergence

- [x] T050 阅读 T01 源事实，拆分其全部超 60 KB source/test，模块专项回归通过；`1885118` T01 passed 且完整结构化工件等价。
- [x] T051 阅读 T05 源事实，拆分其全部超 60 KB source/test，模块回归 `47 passed`；`1885118` T05 passed 且完整结构化工件等价。
- [x] T052 阅读 T07 源事实，拆分其全部超 60 KB source，模块回归 `21 passed`；`1885118` T07 passed 且完整结构化工件等价。
- [x] T053 阅读 T09 源事实，拆分 `frcsd_restriction.py`，multi-evidence 回归 `55 passed`；`1885118` T09 Step1/2/3 passed 且完整结构化工件等价。
- [x] T054 阅读 T10 源事实，拆分 `case_runner.py` 和 `test_t10_contracts.py`，保持四个正式脚本入口及 callable 不变；T10 契约回归 `31 passed`，另 1 个 Windows Bash/WSL 既有失败已在 main 复现。
- [x] T055 [US1] Phase 6 后架构六用例回归 `t10_codesize_complete_6cases_20260711` 为 6/6 passed；最终性能候选另见 T071-T073。

## Phase 7 - Non-T10-chain 60 KB convergence

- [x] T060 按用户 2026-07-11 明确授权，将已废弃 T02 从本轮 60 KB 拆分与验收范围排除；未触碰 T02 源码/测试。
- [x] T061 阅读 T08 源事实，拆分三个超 60 KB source；Tool4/5/6 回归 `24 passed`，另 2 个 Tool5 Windows GPKG 临时文件占用失败已在未修改 main 同平台复现。
- [x] T062 阅读 T11 源事实，拆分 `extract.py`；模块回归 `22 passed`，另 1 个 Windows `csv.field_size_limit(sys.maxsize)` 既有失败已在 main 复现。
- [x] T063 阅读 P01 源事实，拆分两个超 60 KB source 和超线测试；回归 `46 passed`，另 1 个 text-bundle 既有失败已在 main 复现。
- [x] T064 [US3] 扫描并拆分 research 清单中尚未收敛的所有非 T02 超 60 KB 测试文件。
- [x] T065 [US3] 更新 `docs/repository-metadata/code-size-audit.md`，准确登记本轮前后体量、拆分映射与 T02 授权排除快照。
- [x] T066 [US3] 全量扫描 629 个 tracked 受治理文件与 724 个工作树文件，确认排除 Retired T02 后 `>= 61440 bytes = 0`。

## Phase 8 - Final regression & QA

- [x] T070 [US4] 最终六用例正式 run 以 `1885118` 为第一例；该例九阶段全部 passed，阶段合计 `649.910s`。
- [x] T071 [US1] 最终 T10 六用例 `t10_scratch_formal6_v31/t10` 完整回归，六个 Case、54 个 stage 全部 passed。
- [x] T072 [US2] current-main 架构 reference 与 final run 各 `36731` 个 CSV/JSON/GPKG/GeoJSON 工件，missing/extra/changed 均为 `0`。
- [x] T073 [US1] 最终九阶段合计 `1944.274435s <= 1991.603057s`；相对基线下降 `41.426%`、吞吐提升 `70.724%`。
- [x] T074 [US2] 已通过结构化比较核验 CRS、schema、几何 WKB、业务属性与拓扑产物；正式 manifest/stage JSON 提供输入、参数、输出和性能追溯，未执行 silent fix。
- [x] T075 非 T02 全测 `1526 passed, 4 failed`；4 个 T04 失败已在未修改主仓库原样复现。新增等价 helper `9 passed`，wrapper `bash -n` 与 `git diff --check` 通过，既有入口未新增。
- [x] T076 已核验主仓库 HEAD/branch、worktree 列表、正式候选根和 scratch 清理；主仓库仅保留任务前既有的未跟踪 `docs/presentations/project-report-2026/deck/`，本轮未写入主仓库或覆盖正式基线。
- [x] T077 已按 spec FR/SC 完成 completion audit；性能、业务等价、60KB、1885118-first、GIS/QA 和隔离工作树证据均登记于 `research.md` 与 code-size audit。

## Dependencies & Execution Order

- T008-T016 是所有源码写入的阻塞前置。
- T03 -> T04 -> T06 按热点收益顺序执行；每个模块先 characterization，再机械拆分，再性能优化，再 `1885118`。
- T046 是首个大阶段六用例门禁；未通过不得进入剩余主链大规模拆分。
- T050-T054 可按模块顺序执行，但每个模块必须独立通过 `1885118`；T055 是第二个六用例门禁。
- T060-T064 不由 `1885118` 覆盖，必须以模块正式测试证明兼容。
- T065 与所有当前超过 100 KB 文件的拆分必须同轮完成，T066 是代码规模总门禁。
- T070-T077 是最终完成条件，任何一项缺失均不得宣称目标完成。
