# Tasks：T03 全量 Case 准确性闭环

## Phase 1：规格与基线

- [x] T001 阅读仓库、T03、T05、T12 源事实和局部红线。
- [x] T002 建立独立 worktree `codex/t03-accuracy-closure-20260801`。
- [x] T003 冻结三套数据目录、Case 数和输入聚合指纹。
- [x] T004 用当前主干重放 QA 54、legacy T03、legacy T03_Error。
- [x] T005 复跑未合并通用实验方案并记录可复用项与已知回退。
- [x] T006 建立产品、架构、研发、测试、QA 五视角 SpecKit。
- [x] T007 保留正式 65 Case visual baseline，并将 49 条后续用户明确裁决写成按数据快照隔离的机器可读 truth registry。

## Phase 2：测试先行与根因收敛

- [x] T008 增加 `2m` 边界门禁 synthetic/real Case 回归。
- [x] T009 增加 canonical mainNode/alias lookup 回归。
- [x] T010 增加 Class B ownership 正反例回归。
- [x] T011 增加 Direction raw topology、terminal collapse 和 unmatched support 回归。
- [x] T012 增加业务连通性等价与合理/不合理 MultiPolygon 回归。
- [x] T013 增加 `74421922` 复杂场景负保护和 `12777955` 争议隔离。
- [x] T014 增加无效输入几何显式审计和 no-silent-fix 回归。

## Phase 3：实现

- [x] T015 实施共享 `2m` spatial access gate，不放宽其它距离语义。
- [x] T016 实施 deterministic canonical mainNode lookup 与审计。
- [x] T017 实施 Class B junction ownership gate。
- [x] T018 实施 Road-surface 业务连通域、边缘追踪和受约束 regularization。
- [x] T019 实施 Step7 Direction raw topology anchor completeness gate。
- [x] T020 同步 T03/T05/T12 模块源事实和稳定审计字段。

## Phase 4：全量回归与 QA

- [x] T021 运行 T03、T05、T12 全量测试和 T06 全部 T03/T05 消费回归。
- [x] T022 重放 QA 54、legacy T03、legacy T03_Error。
- [x] T023 执行 truth registry gate；确认成功/失败误判均为 0。
- [x] T024 审计所有状态变化和全部残留失败根因。
- [x] T025 执行 CRS、拓扑、几何、追溯、QGIS overlay 和 no-silent-fix 检查。
- [x] T026 执行性能、文件体量、对象 ID、输入文件 hash 和 `git diff --check` 检查。

## Phase 5：交付

- [x] T027 输出验证报告、逐 Case 台账和 QGIS 机器审计/图片索引。
- [x] T028 区分已修改、已验证、待确认并报告任何内网待验证项。

## Phase 6：Scheme A 快照重建

- [x] T029 撤销 QA 当前快照固定“4 正 16 负”及跨快照 CaseID 继承。
- [x] T030 分离 `user_confirmed` 与 `data_audit_target`，冻结历史逐 Case防回退集合。
- [x] T031 修复 QA 当前快照 7 个通用 T03 假拒绝目标，不使用对象 ID 特判。
- [x] T032 验证 QA 当前快照 11 个残留拒绝均有明确、可复核且非 Case 特例的拒绝理由。
- [x] T033 重放 QA 54、legacy T03、legacy T03_Error，并执行逐 Case diff gate。
- [x] T034 执行 CRS、拓扑、几何、追溯、性能、QGIS overlay 和 no-silent-fix 全量门禁。

## Phase 7：T12 QA 真值重建

- [x] T035 对修复后仍 rejected 的 QA Case 重验原始 FRCSD Road/Node、Direction、SWSD 必需通行
  与等价 carrier，不按 T03 reason 直通。
- [x] T036 建立 snapshot-scoped T12 candidates/exclusions/confirmed 台账，不预设 confirmed 数量。
- [x] T037 增加 T12 carrier-complete、算法误拒绝、跨层与输入阻断防误报回归。
- [x] T038 完成 T03/T05/T06/T12 测试、真实数据回归和最终验证报告。
