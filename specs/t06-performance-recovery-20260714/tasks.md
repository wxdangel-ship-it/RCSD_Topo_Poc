# Tasks: T06 六用例业务冻结与性能恢复

## Phase 1 - 基线冻结

- [x] T001 [US1] 记录工作树、commit、Python/GDAL/GEOS、CPU/内存、输入根与冻结目标。
- [x] T002 [US1] 运行 `1885118` 当前版本 Step1/2/3，记录业务指标、wall/CPU/peak RSS。
- [x] T003 [US1] 检查 `1885118` CRS、拓扑、geometry、审计完整性。
- [x] T004 [US1] 顺序运行其余五例并生成六例基线汇总。
- [x] T005 [US1] 生成六例结构化业务指纹/比较输入。

## Phase 2 - 架构与热点诊断

- [x] T006 [US3] 形成 Step3 replay、surface release、hard-gate、ownership/construction 调用图。
- [x] T007 [US3] 记录 cProfile、重复 vector read/write、buffer 次数与阶段耗时。
- [x] T008 [US3] 记录每次 replay 的 RSS 变化和 cache 生命周期。
- [x] T009 [US3] 完成 `analyze.md`，确认接口/入口/体量/源事实无冲突。

## Phase 3 - 等价优化实现

- [x] T010 [US3] 写入前记录所有目标源码/测试文件 bytes。
- [x] T011 [US3] 增加 validation-only/final-publish characterization tests。
- [x] T012 [US3] 分离候选验证与最终 ownership/construction/feature-triplet 发布。
- [x] T013 [US3] 恢复同一 pipeline 内内容寻址 coverage/read context 复用，并设置容量/生命周期边界。
- [x] T014 [US3] 保持 facade、官方 callable、CLI、参数和输出 schema 不变。
- [x] T015 [US3] 运行 T06 相关单元/契约测试与实时 code-size scan。

## Phase 4 - `1885118` 硬门禁

- [x] T016 [US4] 重跑 `1885118` 并确认所有 T06 阶段 passed。
- [x] T017 [US4] 结构化业务差异为 0。
- [x] T018 [US4] CRS、topology、geometry、审计结果不回退。
- [x] T019 [US4] Step1/2、Step3、T06 总耗时恢复到冻结基线。
- [x] T020 [US4] peak RSS 不高于当前版本基线且无迭代增长。

## Phase 5 - 五例与六例验收

- [x] T021 [US2] 按 `605415675 -> 609214532 -> 706247 -> 74155468 -> 991176` 顺序回归。
- [x] T022 [US2] 六例业务结构化差异为 0。
- [x] T023 [US2] 六例逐例和合计 Step1/2、Step3、T06 总耗时达标。
- [x] T024 [US2] 六例 peak RSS 不回退且无 OOM/swap 风险。
- [x] T025 [US2] 汇总修改文件、验证证据、剩余风险与未改范围。

## Execution Order

`T001 -> T002 -> T003 -> T004 -> T005 -> T006..T009 -> T010..T015 -> T016..T020 -> T021..T025`

任何 `T016..T020` 失败都阻断 `T021`；不得先跑五例再补 `1885118` 证据。
