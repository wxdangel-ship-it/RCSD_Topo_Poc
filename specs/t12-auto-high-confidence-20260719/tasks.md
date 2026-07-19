# Tasks：T12 自动高置信质量确认

## Phase 1：规格与源事实

- [x] T001 核对当前 branch、工作区、正式源事实和 1026960 基线。
- [x] T002 在真实 35 个候选上比较 canonical/raw graph 与 portal 策略，形成通用可分规则。
- [x] T003 建立本次 spec/plan/tasks/research/output contract，覆盖产品、架构、研发、测试、QA。
- [x] T004 更新项目级和 T12 模块级正式源事实，移除“无 review confirmed=0”的旧规则。

## Phase 2：测试先行

- [x] T005 写入前检查所有目标 `.py` 当前字节数。
- [x] T006 增加 raw graph 不折叠 main/sub node 的失败测试。
- [x] T007 增加 T07 standard surface portal 与非 T07 spatial portal 测试。
- [x] T008 增加自动 confirmed/excluded、锚点门禁和可选 override 测试。
- [x] T009 更新 runner/output 契约测试：无 review 也不得默认 manual。

## Phase 3：实现

- [x] T010 实现 identity/raw endpoint graph helper。
- [x] T011 实现 T07 surface association、raw portal 和关联审计。
- [x] T012 在 candidate audit 中同时保留 canonical 候选证据和 raw verdict 证据。
- [x] T013 实现自动高置信 decision，外部 review 仅作可选 override。
- [x] T014 扩展 CSV/GPKG/summary/manifest/report 的 decision 与 raw topology 证据。

## Phase 4：回归与 QA

- [x] T015 运行 T12 单元和契约测试。
- [x] T016 使用 1026960 原始数据无 review 验证 35/10/25/0 及完整 ID 集。
- [x] T017 验证显式 review override 兼容和 T10 resume/full contract。
- [x] T018 运行 T10/T12 受影响回归。
- [x] T019 扫描生产源码，证明无 Case/Segment/Road/Node 真值 ID。
- [x] T020 验证 CRS、拓扑、几何语义、审计追溯、性能和 `silent_fix=false`。
- [x] T021 运行源码体量审计、`git diff --check` 和源事实交叉检查。

## Phase 5：交付

- [x] T022 按已修改/已验证/待确认分档回报；不冒充已执行内网全量。
