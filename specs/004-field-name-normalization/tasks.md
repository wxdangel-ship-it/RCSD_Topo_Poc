# Tasks: 外部数据字段名统一归一化

## Phase 1: Setup & Audit

- [x] T001 在 `codex/004-field-name-normalization` 隔离工作树建立 SpecKit 工件。
- [x] T002 核验 997348/1026960 SWSD 与 FRCSD schema 的实际大小写差异。
- [x] T003 生成活动模块外部字段访问与重复 helper 清单，标注内部精确键保留项。

## Phase 2: Foundational

- [x] T004 写入 `tests/utils/test_field_names.py`，先覆盖 casefold、原属性保留、候选优先级、同值重复与冲突失败。
- [x] T005 实现 `src/rcsd_topo_poc/utils/field_names.py` 的共享 `PropertyLookup` 与便捷函数。
- [x] T006 增加静态审计测试，禁止活动模块新增手写 case-insensitive 字段扫描。

## Phase 3: US1 - T03/T04 主链修复

- [x] T007 [US1] 先添加 T03 camelCase Road/Node 失败回归与邻接等价测试。
- [x] T008 [US1] 先添加 T04 camelCase 必填字段、缺值和冲突字段失败回归。
- [x] T009 [US1] 迁移 T03 外部 Node/Road 解析，补齐必填道路拓扑校验。
- [x] T010 [US1] 迁移 T04 外部 Road/Node/面字段解析及 patch id 读取。

## Phase 4: US2 - 仓库统一

- [x] T011 [US2] 让 T00/T08/T06 既有 helper 复用项目共享实现，保持兼容导出面。
- [x] T012 [US2] 迁移 T01/T05/T07/T09/T10/T11/P01/P02 活动或保留路径中的外部字段解析。
- [x] T013 [US2] 审计剩余 `properties.get/props.get`，只保留内部精确 handoff/审计字典并记录理由。

## Phase 5: US3 - 契约与 QA

- [x] T014 [US3] 同步 `docs/architecture/02-data-and-domain-model.md` 与受影响 `INTERFACE_CONTRACT.md`。
- [x] T015 [US3] 执行共享、T03/T04、受影响模块及跨模块测试。
- [x] T016 [US3] 执行真实 schema smoke、CRS/拓扑/几何不变性检查、冲突可追溯检查与性能微基准。
- [x] T017 [US3] 执行全仓源码体量、静态残留、git diff 和入口变更审计；按结果同步 code-size audit（如表事实发生变化）。
