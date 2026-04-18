# Feature Specification: T03 Step67 Contract Formalization

**Feature Branch**: `codex/t03-step67-directional-cut`  
**Created**: 2026-04-18  
**Status**: Draft  
**Input**: User request: “正式审计一次项目需求文档和代码实现，将本轮完善的需求正式的落入仓库需求文档契约。”

## Context

- 当前仓库正式文档仍普遍把 `t03_virtual_junction_anchor` 的正式范围写成“冻结 `Step3` 之上的 `Step4-5` 联合阶段”。
- 但代码、测试与 formal batch 已经形成了稳定的 Step67 事实：
  - `Step6` 负责受约束的几何求解与后处理
  - `Step7` 负责最终 `accepted / rejected` 业务发布
  - `support_only` 在 Step6 合法收敛后可成功
  - Step5 不再提供 hard polygon foreign context
  - Step6 只消费 road-like `1m` foreign mask
  - degree-2 connector `RCSDRoad` 先按 chain 合并，再参与 Step45 分类
- 本轮目标不是把所有求解器细节冻结成契约，而是把已经稳定的**业务边界、状态语义、输出组织、closeout 口径**正式写回仓库文档。

## Thread-Level Clarified Requirement

以下条目为本轮要正式吸收到仓库文档的 clarified requirement：

1. `t03_virtual_junction_anchor` 的当前正式范围升级为冻结 `Step3` 之上的 `Step4-7` clarified formal stage。
2. `Step3` 仍是冻结前置层，不重新定义。
3. `Step45` 继续是前置分类层：
   - `association_class ∈ {A, B, C}`
   - `step45_state ∈ {established, review, not_established}`
   - `support_only` 是稳定业务保守态，不等于算法失败。
4. `Step6` 是受约束几何生成层，不是 cleanup 驱动补救层。
5. `Step7` 主状态是二态：
   - `accepted`
   - `rejected`
6. `V1-V5` 只属于视觉审计层，不再等价于主机器状态。
7. `Step5` 不再生成 hard foreign polygon context；`Step6` 只消费 road-like `1m` hard negative mask。
8. `degree = 2` connector `RCSDNode` 本身不进入 semantic core，但其串接的 candidate `RCSDRoad` 先按 chain 合并，再参与 `required / support / excluded` 分类。
9. 不新增 Step67 CLI；当前 Step67 正式交付仍通过模块内 batch runner 产生，不登记为 repo 官方入口。
10. remaining `707913 / 954218 / 520394575` 当前已人工确认属于输入数据错误，不再视为本轮待修算法问题。

## User Scenarios & Testing

### User Story 1 - 正式文档与当前实现对齐 (Priority: P1)

作为维护者，我需要仓库和模块正式文档能准确反映当前 T03 的正式业务边界，而不是继续停留在 Step45-only 口径。

**Why this priority**: 当前正式文档与代码实现/批量结果已经脱节。

**Independent Test**: 审阅项目级治理文档、模块 README、INTERFACE_CONTRACT 与 architecture 文档是否一致表达当前 Step4-7 clarified formal stage。

### User Story 2 - 只正式化稳定业务边界，不冻结求解器参数 (Priority: P1)

作为维护者，我需要把已经稳定的业务边界写入契约，同时避免把 `20m`、buffer 宽度、cover ratio 等启发式参数误写成长期 source-of-truth。

**Why this priority**: 当前几何实现仍在继续收口，参数还不是正式业务定义。

**Independent Test**: 检查正式文档只写业务职责、输出和状态，不把 `FINAL_CLOSE_M=1.6` 之类实现参数写入契约。

### User Story 3 - 项目级登记同步更新 (Priority: P1)

作为 repo 维护者，我需要项目级治理盘点与模块级正式文档同步更新，避免出现“模块契约已到 Step67，但治理入口仍说只到 Step45”的冲突。

**Why this priority**: 治理入口本身也是 source-of-truth 链的一部分。

**Independent Test**: `docs/PROJECT_BRIEF.md`、`docs/doc-governance/README.md`、`module-lifecycle.md`、`current-module-inventory.md`、`current-doc-inventory.md` 与模块正式文档保持一致。

## Edge Cases

- Step67 已形成稳定实现链，但当前没有官方 CLI；文档必须明确“正式交付存在，但执行入口仍是模块内 batch runner”。
- `step45_foreign_swsd_context.gpkg / step45_foreign_rcsd_context.gpkg` 当前仍保留输出文件名，但可以为空；文档必须避免误导下游把它们当成 hard foreign polygon context。
- `07-step6-readiness-prep.md` 仍保留为预备性历史文档，需要补“已被正式 Step67 契约部分吸收”的说明，避免与新文档冲突。
- `707913 / 954218 / 520394575` 的“输入数据错误”是人工治理口径，不应伪装成当前机器状态字段已正式实现。

## Requirements

### Functional Requirements

- **FR-001**: System MUST formally update project-level and module-level source-of-truth docs to reflect T03 current clarified formal scope as `Step4-7` on top of frozen `Step3`.
- **FR-002**: System MUST define `Step7` machine state as binary `accepted / rejected`, while keeping `V1-V5` as visual audit classes only.
- **FR-003**: System MUST formalize `support_only` as Step45 conservative intermediate state that can still converge to final acceptance in Step67.
- **FR-004**: System MUST formalize Step5/Step6 foreign boundary as “Step5 no hard polygon context; Step6 road-like `1m` hard mask only”.
- **FR-005**: System MUST formalize degree-2 `RCSDRoad` chain merge as an upstream Step45 classification rule, without angle gating.
- **FR-006**: System MUST keep Step67 out of repo official CLI/entrypoint registry in this round.
- **FR-007**: System MUST add a formal Step67 closeout/architecture record without pretending all solver heuristics are frozen contract.
- **FR-008**: System MUST record the three manually confirmed input-data-error cases in thread deliverables, not as a new formal machine-state field.

### Key Entities

- **Step45 Conservative Intermediate State**: `association_class / step45_state` 为 Step67 提供前置分类与约束，而不是最终发布结论。
- **Step67 Clarified Formal Stage**: 当前 T03 正式业务边界，覆盖 Step6 geometry + Step7 acceptance，但不冻结 solver 参数。
- **Visual Audit Class**: `V1-V5`，用于人工目视审计，不等同机器状态。
- **Road-Like Hard Foreign Mask**: 当前唯一正式 hard negative mask 来源，即 Step6 消费的 `excluded_rcsdroad_geometry -> 1m mask`。

## Success Criteria

### Measurable Outcomes

- **SC-001**: `README / INTERFACE_CONTRACT / architecture/*` 一致表达 T03 当前正式范围为冻结 `Step3` 之上的 `Step4-7 clarified formal stage`。
- **SC-002**: 项目级治理文档不再把 T03 记为 “Step45 only”。
- **SC-003**: 正式文档明确 `accepted / rejected` 与 `V1-V5` 的分层关系。
- **SC-004**: 正式文档明确 Step67 仍无官方 CLI，但已有正式交付与 closeout 证据。
- **SC-005**: 正式文档不冻结 `20m/buffer/ratio` 等 solver 参数为长期业务契约。
