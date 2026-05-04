# T04 Step4 Arbiter Rearchitecture · SpecKit 任务书

**Branch**：`codex/t04-step4-arbiter-rearchitecture`
**Created**：2026-05-04
**Status**：specify
**Module**：`modules/t04_divmerge_virtual_polygon/`
**Driver Issue**：T04 Step4 正向 RCSD / 主证据 / Reference Point 候选被后续阶段覆盖、降级或继承；698389 当前 `surface_scenario_type=main_evidence_with_rcsd_junction` 但 RCSD 与 SWSD 趋势不一致。

## 文件结构

- `README.md`：本入口（任务书索引 + 工作树纪律）
- `spec.md`：产品视角 + 业务需求 + 验收标准（specify 阶段产物）
- `plan.md`：架构 / 研发 / 测试 / QA 视角 + 4 层方案 + 前置任务（plan 阶段产物）
- `tasks.md`：可执行任务列表（tasks 阶段产物，按依赖顺序）

## 与硬约束的关系

参见 `AGENTS.md`：

- §1.2：本任务**会**修订 `INTERFACE_CONTRACT.md §3.4 / §3.5 / §4.4`、`architecture/04-solution-strategy.md`、`architecture/10-quality-requirements.md`；属于项目级 / 模块级源事实变更，必须走 SpecKit 全流程。
- §1.3：本任务**不**新增 repo 官方 CLI / 新执行入口；模块内 Python 稳定执行面 `run_t04_step14_batch / run_t04_step14_case / run_t04_internal_full_input` 签名不变。
- §1.4 / §3：本任务命中文件体量约束（多文件接近 100 KB），**必须先做拆分前置任务**并同轮更新 `docs/repository-metadata/code-size-audit.md`。
- §5：本任务保持 `surface_scenario_type / rcsd_alignment_type / main_evidence_type / evidence_source / position_source` 等所有值域不变；只改"由哪一层发布"。
- §6：测试 / QA 视角在 `plan.md §3.4 / §3.5` 显式覆盖；缺失视为任务书未就绪。
- §7：本任务不涉及内网执行；验证基于本地工件与 `tests/modules/t04_divmerge_virtual_polygon/`。

## 工作树纪律

- 在 `codex/t04-step4-arbiter-rearchitecture` 分支独立推进，不直接 push 到 `main`。
- 任务书三件套落盘后先 commit 并停机汇报，再进入 implement。
- implement 阶段遵守 `.agents/skills/default-imp/SKILL.md`：最小必要改动、不顺手重构、区分"已修改 / 已验证 / 待确认"。
- 每个 `tasks.md` 中的 task 完成后，必须更新该 task 状态并跑对应测试子集。

## 风格参考

格式与篇幅参考：

- `specs/t04-positive-rcsd-selector-redesign-speckit/{spec,plan,tasks}.md`
- `specs/t04-step14-speckit-refactor/{spec,plan,tasks}.md`

## 入口

新工作树创建后，按 `tasks.md` 的 T-01 起步。
