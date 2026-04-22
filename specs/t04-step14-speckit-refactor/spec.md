# Feature Specification: T04 Step1-4 Speckit Refactor

**Feature Branch**: `codex/t04-step14-speckit-refactor`  
**Created**: 2026-04-20  
**Status**: Implemented  
**Input**: User request to正式启动 T04 Step1-4 的文档落仓、架构规划、代码重构与 Step4 可视审计输出。

## Context

- 当前 repo `Active` 模块只有 `t01_data_preprocess`、`t02_junction_anchor`、`t03_virtual_junction_anchor`。
- 线程级 `REQUIREMENT.md` 已完成 T04 Step1-4 定稿，但 repo 内还没有 T04 的正式模块文档面。
- T02 Stage4 已有可复用的 Step2/3/4 核心算法；T03 已有成熟的 case-package / batch / review png / flat mirror / summary 组织方式。
- 本轮目标不是推进 Step5-7，而是把已确认的 Step1-4 正式沉淀成 repo source-of-truth，并完成一轮可运行的模块化实现。

## Thread-Level Clarified Requirement

1. T04 是原 T02 Stage4 的模块化继承与重构版，但本轮正式范围只做到 Step1-4。
2. 文档必须先落仓，再开始代码重构。
3. 代码结构按领域能力分层，不把临时 `step1234_*` 当作主结构。
4. T04 本轮必须提供 Step4 review PNG、flat mirror、review index、review summary。
5. 新模块当前不新增 repo 官方 CLI；以模块内 runner 与测试调用完成本轮交付。
6. Step4 必须显式表达 `STEP4_OK / STEP4_REVIEW / STEP4_FAIL`，不沿用 `accepted / rejected` 作为主标签。

## User Scenarios & Testing

### User Story 1 - T04 正式文档落仓 (Priority: P1)

作为维护者，我需要在 repo 内看到 T04 的正式模块 README、INTERFACE_CONTRACT 与 architecture 文档，保证线程级需求不再只停留在同步目录。

**Independent Test**: 审阅 `modules/t04_divmerge_virtual_polygon/*` 与项目级治理索引，确认 T04 已纳入正式文档链路。

### User Story 2 - Step1-4 模块化重构 (Priority: P1)

作为实现者，我需要一个按 admission / local_context / topology / event_interpretation / review_render / outputs 分层的 T04 模块，而不是继续依赖 T02 Stage4 的大一统 orchestrator。

**Independent Test**: 运行 T04 batch runner，能稳定产出 Step1-4 case 结果与 Step4 review 工件。

### User Story 3 - Step4 可视审计输出 (Priority: P1)

作为质检者，我需要在 batch run root 下直接查看每个 case 的 Step4 overview、event-unit review、flat mirror、index 与 summary。

**Independent Test**: 运行后生成 `cases/<case_id>/step4_review_overview.png`、`step4_review_flat/*.png`、`step4_review_index.csv`、`step4_review_summary.json`。

## Edge Cases

- `complex / continuous 128` 需要按 node 级 event unit 拆分，但本轮仍不得推进 Step5-7。
- Step4 允许 `reverse tip` 受控重试，但必须显式留痕。
- RCSD 缺失不阻断 Step1 准入，也不在 Step2 定义 RCSD 负向语义。
- 当前 T04 不新增 repo 官方 CLI，因此不能修改 `entrypoint-registry.md` 去发明新的正式入口。

## Requirements

### Functional Requirements

- **FR-001**: System MUST create a new formal module `t04_divmerge_virtual_polygon` with module docs and source layout.
- **FR-002**: System MUST write repo-level governance/index docs so T04 enters the formal module inventory.
- **FR-003**: System MUST implement Step1 candidate admission matching thread-level Step1 rules.
- **FR-004**: System MUST implement Step2 local context construction with `PatchID -> DriveZone / DivStrip` and `50m/200m/complex 200m` recall windows.
- **FR-005**: System MUST implement Step3 topology skeletonization with member nodes, passthrough nodes, branches, main pair, and continuous chain augmentation.
- **FR-006**: System MUST implement Step4 fact event interpretation with event-unit split, evidence ownership, event reference discovery, positive RCSD selection, and consistency check.
- **FR-007**: System MUST materialize Step4 review outputs in case-level and flat-mirror layouts.
- **FR-008**: System MUST keep Step5-7 out of current formal scope and not add new repo official entrypoints in this round.

### Key Entities

- **T04 Case Package**: 包含 `manifest.json / size_report.json / drivezone.gpkg / divstripzone.gpkg / nodes.gpkg / roads.gpkg / rcsdroad.gpkg / rcsdnode.gpkg` 的单 case 输入目录。
- **Admission Result**: Step1 的准入结果与原因，不承接后续解释失败。
- **Local Context**: Step2 产出的 DriveZone-bounded 局部世界与 SWSD 负向上下文。
- **Topology Skeleton**: Step3 产出的 member / passthrough / branch / chain augmentation 结构结果。
- **Event Unit**: Step4 解释层的最小事实事件单元，拥有独立证据与独立参考位置。
- **Step4 Review Row**: 平铺 PNG、CSV 索引与 JSON summary 使用的稳定摘要行。

## Success Criteria

### Measurable Outcomes

- **SC-001**: repo 文档链路中出现 T04 模块，并明确当前正式范围是 Step1-4。
- **SC-002**: T04 source code 以领域能力分层，不再依赖单一超大 orchestrator。
- **SC-003**: 至少一轮本地 batch 能产出 Step4 overview、event-unit review、flat mirror、index、summary。
- **SC-004**: 本轮实现不触发新的 repo 官方入口新增，不进入 Step5-7 实现。
