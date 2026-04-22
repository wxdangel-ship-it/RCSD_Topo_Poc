# 仓库根目录 `AGENTS.md` 修正草稿（待 GPT 二次审计）

> 本文件是 **草稿**，不是当前生效的 `AGENTS.md`。
>
> 当前生效版本仍为仓库根目录 `AGENTS.md`。本草稿用于交叉审计，确认后再决定是否替换。
>
> 配套审计依据：`docs/doc-governance/audits/2026-04-21-agents-md-audit.md`

---

下方"---  BEGIN DRAFT  ---"和"---  END DRAFT  ---"之间，是建议替换为新 `AGENTS.md` 的全部正文。

---  BEGIN DRAFT  ---

# 仓库级执行规则

本文件是 Agent 进入本仓库的第一份硬规则面。`AGENTS.md` 只放**会话级硬规则**，不放流程长描述、不放会过期的事实清单、不放环境信息表。

> 优先级口径：本节内"§1 硬停机触发"高于一切；§2-§7 之间冲突时，由"硬停机触发"裁定。

## §1 硬停机触发（任一命中必须立刻停机并回报）

发生以下任一情况，**禁止继续写代码或文档**，必须先停下并向用户回报：

1. 项目级源事实之间、模块级源事实之间、或源事实与任务书之间存在冲突。
2. 当前任务书未授权，但本轮改动会影响：
   - 任务书显式排除的模块、目录或 spec；
   - 模块官方对外接口（`INTERFACE_CONTRACT.md`、CLI 子命令、入口脚本签名）；
   - 项目级源事实文档（`SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/architecture/*`、`docs/doc-governance/module-lifecycle.md`）。
3. 当前任务书未授权，但本轮会**新增执行入口脚本**（`Makefile` 目标、`scripts/`、`tools/`、模块内 `__main__.py` 等）。
4. 本轮会让某个源码 / 脚本文件**首次跨过 100 KB 阈值**，或会向**已超阈值文件**追加任何内容。
5. 数据现象与已确认的字段语义冲突，准备据此反推上游字段含义并固化为强规则。
6. 用户提供的命令是 Windows 路径或 WSL 路径之一，但当前会话所处的 shell 环境与之不一致（例如用户给的是 WSL 路径但当前会话是 PowerShell）。
7. `entrypoint-registry.md` 与 `src/rcsd_topo_poc/cli.py`、`scripts/` 或模块契约的事实不一致。

回报内容必须包括：触发的条款编号、当前事实、缺失/冲突点、建议的下一步选项。

## §2 阅读链路与源事实

- 主阅读入口只有一处：`docs/doc-governance/README.md`。本文件不再维护第二份阅读顺序，所有"先读什么后读什么"以该入口为准。
- 项目级源事实集合：`SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/architecture/*`、`docs/doc-governance/module-lifecycle.md`。
- 模块级源事实集合：`modules/<module>/architecture/*` 与 `modules/<module>/INTERFACE_CONTRACT.md`。
- `specs/*` 是 spec-kit 变更工件，不是源事实；任务未显式要求时不当作 day-0 主阅读材料。
- 默认主阅读 / 主搜索路径**不包含**：`outputs/`、`outputs/_work/`、`.claude/worktrees/`、`.venv/`、`.idea/`、临时审计工件。仅在任务明确要求时进入。

## §3 结构与体量约束（强约束，对应 §1.4）

- **阈值**：单个 `.py` / `.sh` / `.cmd` / `.ps1` / `.ts` / `.js` / `.bat` 等源码 / 脚本文件，硬阈值 `100 KB`。`tests/`、`tools/`、`scripts/` 同样适用。
- **前置自检（必须）**：在对任何源码 / 脚本文件追加内容前，先确认该文件**当前**体量。可用 `Get-ChildItem`（PowerShell）、`stat -c%s`（POSIX）或等效手段。
- **三类禁止行为（命中即 §1.4 停机）**：
  1. 向已超过 `100 KB` 的文件追加任何内容（即使是注释）。
  2. 让某个原本未超阈值的文件因本轮新增首次跨过 `100 KB`。
  3. 拆分或迁移已超阈值文件时，未在**同一轮**更新 `docs/repository-metadata/code-size-audit.md`。
- **允许的继续推进路径**（在停机回报后由用户授权）：
  - 提交"拆分计划"：列出目标文件、拆分后子模块、契约迁移、测试迁移、风险点。
  - 提交"豁免说明"：说明为什么本轮无法拆分、本次新增内容的最小化策略、何时启动拆分。豁免说明必须**同轮**更新 `code-size-audit.md`。
- **登记同步（必须）**：任何让 `code-size-audit.md` 表内容应改变的轮次，必须同轮修改该表，否则视为治理缺口、本轮不允许 close。
- **细则**：见 `docs/repository-metadata/code-boundaries-and-entrypoints.md`，凡涉及体量、入口或依赖治理的改动**必须先读**该文件。

## §4 范围与变更边界

- 无明确任务书时，不创建具体业务模块实现，不修改未来模块的接口假设，不把骨架治理顺手扩大为业务算法开发。
- 任务书显式排除的模块、目录、spec 一律视为保护区；除非用户重新授权，不得顺手触碰。
- 不在 `main` 上直接做中等及以上结构化治理变更；该类变更优先走 spec-kit。
- 不修改与当前任务无关的代码、注释、文档、命名和结构。
- 不删除未完全理解的注释、历史逻辑或兼容代码。
- 模块根目录**禁止**新增 `SKILL.md`；标准可复用流程统一放 repo root `.agents/skills/<skill-name>/SKILL.md`。
- `modules/_template/` 仅作为模板，不是业务模块，不参与生命周期盘点。

## §5 数据语义与字段管控

- 禁止根据局部样本、人工真值或单次冒烟结果，自行反推上游字段语义并直接固化为强规则；命中时按 §1.5 停机。
- 未在项目 / 模块源事实文档中正式启用的输入字段，**不得**进入 Step1 / Step2 强规则。
- 字段一旦正式启用，**必须**在同一轮把该字段写入项目级约束与对应模块契约，并说明：当前可用语义、适用范围、未确认边界。
- GIS / 拓扑 / 空间数据相关任务，必须显式覆盖以下检查项（缺一项即视为未完成）：
  - CRS 与坐标变换正确性；
  - 拓扑一致性（不允许 silent fix）；
  - 几何语义可解释性；
  - 审计可追溯性（输入、参数、输出、运行环境可定位）；
  - 性能可验证性。
  详细质量基线见 `docs/architecture/10-quality-requirements.md`，必要时调用 `qgis-auto-visual-check` Skill 进行复核。

## §6 流程路由

- 默认编程流程：repo root `.agents/skills/default-imp/SKILL.md`。本文件不重复列出 default-imp 守则，以该 SKILL 为唯一真相。
- 升级触发：任务边界不清、影响扩大、业务口径不清，从 default-imp 升级为 Spec Kit。
- 大型修改、需求新增、跨模块重构强制走 Spec Kit。
- 完成回报最小集（强制）：每轮交付必须区分 **已修改 / 已验证 / 待确认** 三档，并列出修改的文件路径与每个文件的目的。"看起来应该可以"不得表述为"已经修复"。
- 如需 GPT 进一步阅读，先把材料整理为文本放入指定目录，再回报路径与希望 GPT 判断的问题。

## §7 执行环境与边界

- 执行环境**不预设**任何默认 shell；当前会话的 shell（PowerShell / bash / WSL）以系统注入信息为准。涉及跨盘 / 跨环境路径时，按 §1.6 处理。
- 跨盘符路径换算与 `TestData/POC_Data` 根目录约定见 `docs/repository-metadata/path-conventions.md`（若该文件尚未建立，使用当前生效的旧 `AGENTS.md` line 11-13 内容作为临时真相，并把"建立 path-conventions.md"列为治理缺口）。
- Agent 可执行范围：外网验证、外网数据检查、本地工作区操作。
- Agent 不可自行执行：内网环境、内网数据拉取、内网命令；除非用户在当轮明确提供了可执行的内网访问能力。
- 不得把内网操作误表述为自己已实际执行。

## §8 文档语言

- 仓库内文档默认中文；参数、代码、命令、路径、模块标识、配置键、接口字段可保留英文。
- 本文件本身使用中文；不在常规变更轮次中改写为英文。

---  END DRAFT  ---

## 草稿内部说明（不进入正式 `AGENTS.md`，仅供 GPT 审计参考）

### 与现行版本的主要差异

1. **加分组与编号**：8 个 § 段，§1 是硬停机触发集中段。
2. **代码体量规则升级**：从单条 + 事后触发，升级为"前置自检 + 3 条禁止 + 同轮登记 + §1.4 停机"。
3. **删除 CodeX 默认轻量编码守则段**：用一行强引用 `default-imp/SKILL.md` 替代，消除双源真相。
4. **WSL/盘符外置**：本文件不再写默认 shell，改为按当前会话事实判断；详细换算迁移到 `docs/repository-metadata/path-conventions.md`（草稿建议同步建立此文件）。
5. **GIS 质量改为 5 项可勾选清单**：删除"顶级 GIS 工程师"修辞。
6. **任务级保护区去掉 T02 具体例子**：抽象为"任务书显式排除的范围"。
7. **完成回报标准升级为强制项**："已修改 / 已验证 / 待确认"从建议变成必须。
8. **阅读链路单源化**：本文件只指 `doc-governance/README.md`，不再并列维护排序。

### 配套建议（不在 `AGENTS.md` 内，但建议同步推动）

- 在 `pre-commit` / CI 中加一道脚本：staged 中任一 `.py/.sh/.ps1/.cmd/.ts/.js/.bat` 文件 ≥ 100 KB 时，必须同 commit 修改 `docs/repository-metadata/code-size-audit.md`，否则拒绝。
- `code-size-audit.md` 的"审计日期"改为脚本自动刷新（例如 `make audit-codesize`），并把该命令登记到 `entrypoint-registry.md`。
- 建立 `docs/repository-metadata/path-conventions.md`，把当前 `AGENTS.md` 第 11-13 行内容迁过去并补充非 WSL 场景。

### 仍待 GPT 二次确认的开放问题

1. 100 KB 阈值是否要下调到 60 KB 或 80 KB？
2. 是否要补"行数阈值"（例如 1500 行）作为字节阈值之外的并行约束？
3. `t00_utility_toolbox` 是否值得在 `AGENTS.md` 加一行"工具优先调用"提示？
4. `default-imp/SKILL.md` 的"修订卡"是否要在 `AGENTS.md` §6 内显式列为"边界不清时的强制前置动作"？
5. §1 硬停机触发 7 条，是否还需要补充新触发？例如"测试缺失但宣称已验证"。
