# Feature Specification: Repository Governance Realignment

**Feature Branch**: `002-repo-governance-realignment`
**Created**: 2026-04-14
**Status**: Draft
**Input**: User description: "回到原始项目契约，在当前同一分支上，完成仓库级 + 除 T02 外模块级的治理修正；本轮不得介入 T02 模块正文治理与实现。"

## Summary

本轮不是新增治理体系，也不是业务开发。目标是回到 repo root `AGENTS.md` 已声明的原始契约，把仓库级入口、项目级 source-of-truth、模板与非 T02 模块文档、仓库元数据与入口注册表修回“可执行、可阻断、低歧义”的状态。

本轮只修治理漂移，不扩展业务口径；尤其不进入 `modules/t02_junction_anchor/**`、`src/rcsd_topo_poc/modules/t02_junction_anchor/**` 与 `specs/t02*` 的正文治理或实现修改。

## Original Contract

本轮治理修正必须回到以下原始契约：

1. repo root `AGENTS.md` 是仓库级 durable guidance，而不是项目真相主表面。
2. 主阅读链路是：
   - 先读 `docs/doc-governance/README.md`
   - 需要理解仓库结构时再读 `docs/repository-metadata/README.md`
3. 项目级源事实优先级以 `SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/architecture/*`、`docs/doc-governance/module-lifecycle.md` 为准。
4. 模块级源事实以 `modules/<module>/architecture/*` 与 `INTERFACE_CONTRACT.md` 为准。
5. 中等及以上结构化治理变更优先走 spec-kit。
6. 默认禁止新增执行入口；如确需新增，必须有任务书批准并登记 registry。
7. `modules/_template/` 只是模板，不是业务模块。
8. 不得把治理轮次扩大成业务算法开发。

## Current Drift

当前已确认的漂移点包括：

1. `AGENTS.md`、`docs/doc-governance/README.md`、`docs/repository-metadata/README.md` 的阅读链路存在循环和并列主入口问题。
2. 项目级文档中同时存在“没有正式业务模块”和“已有正式模块”的冲突叙述。
3. `t00 / t01 / t02` 在项目级清单、生命周期和摘要文档中的口径不一致。
4. `_template` 仍使用过时的模块级 `python -m rcsd_topo_poc.modules.<module_id>` 入口示意。
5. `entrypoint-registry.md` 与真实 `cli.py` / `scripts/` 已不一致。
6. `code-size-audit.md` 已明显失真。
7. outputs / `_work` / `.claude/worktrees` / `.venv` 等不应进入主阅读路径的内容，尚未在仓库级规则中被明确排除。

## Scope

### In Scope

- `AGENTS.md`
- `SPEC.md`
- `docs/PROJECT_BRIEF.md`
- `docs/doc-governance/*`
- `docs/repository-metadata/*`
- `docs/architecture/*` 的项目级一致性修正
- `modules/_template/*`
- `modules/t00_utility_toolbox/*`
- `modules/t01_data_preprocess/*`
- `specs/002-repo-governance-realignment/*`
- 本轮治理修复输出到 `outputs/_work/repo_governance_realign_20260414_142216/`

### Out of Scope

- `modules/t02_junction_anchor/**`
- `src/rcsd_topo_poc/modules/t02_junction_anchor/**`
- `specs/t02*`
- `scripts/t02*`
- 任何 T02 模块正文、T02 实现、T02 专项 spec
- 新增业务实现
- 新增业务模块
- 新增 day-0 主入口文件
- 新发明生命周期分类体系或新的治理体系

## User Scenarios & Testing

### User Story 1 - CodeX 进入仓库后能按原始链路稳定阅读 (Priority: P1)

作为进入仓库的新线程，我需要从 `AGENTS.md -> docs/doc-governance/README.md -> docs/repository-metadata/README.md（按需）` 这条链路稳定进入，而不是在多个入口间循环跳转。

**Independent Test**: 仅检查三份入口文件，就能明确 day-0 先读什么、何时按需读结构元数据、哪些不是主阅读路径。

**Acceptance Scenarios**:

1. **Given** 新线程从 repo root 进入仓库，**When** 它读取 `AGENTS.md`，**Then** 能明确知道先读 `docs/doc-governance/README.md`，并且只有在需要理解结构时再读 `docs/repository-metadata/README.md`。
2. **Given** 新线程已读治理入口，**When** 它继续阅读 `docs/doc-governance/README.md`，**Then** 不会再被反向要求回到另一个并列主入口去重新建立 day-0 路径。

### User Story 2 - 项目级治理口径与仓库现实一致，但不侵入 T02 正文 (Priority: P1)

作为治理维护者，我需要让项目级 source-of-truth 对 `t00 / t01 / t02` 的项目级表述一致，同时只对 T02 做最小必要的项目级状态说明，不修改 T02 模块正文。

**Independent Test**: 仅检查 `SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/architecture/*`、`module-lifecycle.md`、`current-module-inventory.md`，就能确认不再同时存在“无正式模块”和“已有正式模块”的冲突叙述。

**Acceptance Scenarios**:

1. **Given** 项目级文档存在初始化阶段旧叙述，**When** 本轮修正完成，**Then** 项目级文档必须与当前仓库现实一致，不再宣称“当前没有正式业务模块”。
2. **Given** T02 当前正在独立重构，**When** 本轮修正完成，**Then** 项目级文档只能对 T02 写最小必要状态说明，不修改其模块正文。

### User Story 3 - 模板与非 T02 模块再次成为可信治理表面 (Priority: P2)

作为后续模块维护者，我需要 `_template`、`t00`、`t01` 的文档边界与当前 repo-level CLI / root scripts 方式一致，这样后续不会沿用错误入口模式继续扩散漂移。

**Independent Test**: 仅检查 `_template`、`t00`、`t01` 的 `AGENTS.md / README.md / INTERFACE_CONTRACT.md`，即可判断职责边界与入口说明是否一致。

**Acceptance Scenarios**:

1. **Given** `_template` 当前仍写着过时入口示意，**When** 本轮修正完成，**Then** 模板必须改回符合当前仓库入口治理方式的表述。
2. **Given** `t00` 是工具集合模块、`t01` 是正式业务模块，**When** 本轮修正完成，**Then** 两者的文档边界必须与模板角色相容，但不新增业务范围。

## Requirements

### Functional Requirements

- **FR-001**: System MUST keep `AGENTS.md` as repository-level durable guidance and MUST NOT turn it into a project-truth summary or task log.
- **FR-002**: System MUST preserve the original read path `AGENTS.md -> docs/doc-governance/README.md -> docs/repository-metadata/README.md (on demand)` and eliminate circular guidance.
- **FR-003**: System MUST make source-of-truth conflict handling explicit: if project-level or module-level source documents conflict, execution MUST stop and request user confirmation.
- **FR-004**: System MUST state that `outputs/`、`outputs/_work/`、temporary audit artifacts、`.claude/worktrees/` and `.venv/` are not source-of-truth and are excluded from the main reading/search path.
- **FR-005**: System MUST keep the “no new entrypoint by default” rule and reconnect it to `docs/repository-metadata/entrypoint-registry.md`.
- **FR-006**: System MUST refresh project-level governance docs so they no longer conflict on current formal modules and project phase.
- **FR-007**: System MUST describe `t00_utility_toolbox` as a governed tooling module / non-business production module, without inventing a new lifecycle system.
- **FR-008**: System MUST realign `_template`、`t00`、`t01` docs with repo-level CLI / root scripts entrypoint reality.
- **FR-009**: System MUST refresh `entrypoint-registry.md` and `code-size-audit.md` using real repository state, without changing T02 code or T02 module docs.
- **FR-010**: System MUST NOT modify any file under `modules/t02_junction_anchor/**`、`src/rcsd_topo_poc/modules/t02_junction_anchor/**`、`specs/t02*` or `scripts/t02*`.

## Risks & Stop Conditions

- 如果发现项目事实冲突无法仅靠最小一致性修正解决，必须停止并请求用户拍板。
- 如果某项修复必须进入 T02 禁止路径，必须停止，不得越界。
- 如果允许路径中已有未提交改动与本轮治理修复直接冲突，必须保留原改动并在汇报中显式列出。

## Success Criteria

- **SC-001**: `AGENTS.md` 仍是 durable guidance，且增加了可执行的阻断规则、排除路径和范围保护。
- **SC-002**: `AGENTS.md -> docs/doc-governance/README.md -> docs/repository-metadata/README.md（按需）` 的阅读链路真实成立，不再循环打架。
- **SC-003**: 项目级文档不再同时出现“无正式模块”与“已有正式模块”的冲突叙述。
- **SC-004**: `_template`、`t00`、`t01` 的入口说明与角色边界与当前仓库真实方式一致。
- **SC-005**: `entrypoint-registry.md` 与真实 `cli.py` / `scripts/` 基本一致，`code-size-audit.md` 反映当前超阈值文件。
- **SC-006**: 本轮修改路径全部位于允许范围内，禁止路径无改动。
