# 仓库级执行规则

本文件是 Agent 进入本仓库的第一份硬规则面。`AGENTS.md` 只放**会话级硬规则**，不放流程长描述、不放会过期的事实清单、不放环境信息表。

> 优先级口径：本节内"§1 硬停机触发"高于一切；§2-§8 之间冲突时，由"硬停机触发"裁定。

## §1 硬停机触发（任一命中必须立刻停机并回报）

发生以下任一情况，**禁止继续写代码或文档**，必须先停下并向用户回报：

1. 项目级源事实之间、模块级源事实之间、或源事实与任务书之间存在冲突。
2. 当前任务书未授权，但本轮改动会影响：
   - 任务书显式排除的模块、目录或 spec；
   - 模块官方对外接口（`INTERFACE_CONTRACT.md`、CLI 子命令、入口脚本签名）；
   - 项目级源事实文档（`SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/architecture/*`、`docs/doc-governance/module-lifecycle.md`）。
3. 当前任务书未授权，但本轮会**新增长期保留的正式执行入口**：包括 `Makefile` 常驻目标、`scripts/` 与 `tools/` 下的常驻命令、模块内 `__main__.py`、`run.py`、CLI 子命令，以及任何应登记到 `docs/repository-metadata/entrypoint-registry.md` 的入口。本条**不**针对一次性实验脚本、本地临时调试脚本、局部分析脚本（这类仍受 §4 范围边界约束，但不触发本条停机）。
4. 本轮会让某个源码 / 脚本文件**首次跨过 100 KB 阈值**，或会向**已超阈值文件**追加任何内容。
5. 数据现象与已确认的字段语义冲突，准备据此反推上游字段含义并固化为强规则。
6. 用户提供的命令是 Windows 路径或 WSL 路径之一，但当前会话所处的 shell 环境与之不一致（例如用户给的是 WSL 路径但当前会话是 PowerShell）。
7. 本轮属于**涉及入口变更的任务**（新增 / 删除 / 重命名 / 改变官方调用方式的入口），但 `entrypoint-registry.md` 与 `src/rcsd_topo_poc/cli.py`、`scripts/` 或模块契约的事实不一致。常规非入口任务无需主动核对 registry，不在本条触发范围内。

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
- 不在 `main` 上直接做中等及以上结构化治理变更；该类变更优先走 SpecKit。
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

### §6.1 默认编程流程（default-imp）

- 默认编程流程：repo root `.agents/skills/default-imp/SKILL.md`。本文件不重复列出 default-imp 全套守则，以该 SKILL 为唯一真相。
- 适用范围：小中型编程任务、边界清晰、可通过最小改动解决的问题。
- 自动升级触发：任务执行中如发现边界不清、影响扩大、业务口径不稳，必须从 default-imp 升级为 SpecKit 模式（见 §6.2）。

### §6.2 SpecKit 模式（正式大型任务的默认模式）

- 当 GPT 向 CodeX 下发**正式大型任务书**时，**默认采用 SpecKit 模式**。
- "正式大型任务"至少包括：
  - 需求新增；
  - 跨模块重构；
  - 影响正式业务口径的修改；
  - 需要明确 `specify / plan / tasks` 的任务。
- 不属于上述范畴的小中型编程任务**不强行**走 SpecKit，仍可走 default-imp。
- SpecKit 主流程固定为：`specify / plan / tasks / implement`。

### §6.3 SpecKit 模式下的多职责覆盖

仅适用于 §6.2 定义的正式大型任务，不强加到 default-imp 任务。

- SpecKit 任务书的组织必须覆盖以下 5 类职责视角：
  - 产品（Product）
  - 架构（Architecture）
  - 研发（Development）
  - 测试（Testing）
  - QA（Quality Assurance）
- 这是**任务书组织视角 / 执行分工视角**，不要求物理上生成 5 个独立线程或子 Agent。具体形式可以是：
  - 主 Agent + 多个子 Agent；
  - 显式多 Agent 协同；
  - 单 Agent 但任务书章节按上述 5 类职责显式划分。
- 任务书必须显式体现上述职责覆盖；**不允许缺失测试与 QA 视角**。任何缺失即视为任务书未就绪，不得进入 implement 阶段。

### §6.4 default-imp 与 SpecKit implement 阶段的共用关系

- `default-imp` **不是** SpecKit 的替代品；SpecKit 也**不取消** `default-imp` 的存在价值。
- 在 SpecKit 模式下，`default-imp` 的作用域被限定为 **implement 阶段的具体编码执行层**：
  - SpecKit 负责 `specify / plan / tasks / implement` 的主流程；
  - `default-imp` 负责 implement 阶段的轻量执行纪律。
- SpecKit 模式的 implement 阶段，**默认遵循** `default-imp` 的关键约束：
  - 不脑补需求；
  - 只做当前目标的最小必要改动；
  - 不顺手重构无关代码；
  - 不修改与当前任务无关的注释、文档、命名和结构；
  - 不删除未完全理解的历史逻辑或兼容代码；
  - 优先简单、可验证、可回退的实现；
  - 结果要区分"已修改 / 已验证 / 待确认"。
- 严禁两种误读：
  - "走了 SpecKit 就不再需要 default-imp"——错误，implement 阶段仍受其约束；
  - "default-imp 可以替代 SpecKit"——错误，正式大型任务必须走 SpecKit 主流程。

### §6.5 完成回报最小集（强制）

- 每轮交付必须区分 **已修改 / 已验证 / 待确认** 三档，并列出修改的文件路径与每个文件的目的。
- "看起来应该可以"不得表述为"已经修复"。
- 如需 GPT 进一步阅读，先把材料整理为文本放入指定目录，再回报路径与希望 GPT 判断的问题。

## §7 执行环境与边界

- 执行环境**不预设**任何默认 shell；当前会话的 shell（PowerShell / bash / WSL）以系统注入信息为准。涉及跨盘 / 跨环境路径时，按 §1.6 处理。
- 跨盘符路径换算与 `TestData/POC_Data` 根目录约定见 `docs/repository-metadata/path-conventions.md`（若该文件尚未建立，使用历史 `AGENTS.md` 中的盘符与测试数据根目录约定作为临时真相，并把"建立 path-conventions.md"列为治理缺口）。
- Agent 可执行范围：外网验证、外网数据检查、本地工作区操作。
- Agent 不可自行执行：内网环境、内网数据拉取、内网命令；除非用户在当轮明确提供了可执行的内网访问能力。
- 不得把内网操作误表述为自己已实际执行。

## §8 文档语言

- 仓库内文档默认中文；参数、代码、命令、路径、模块标识、配置键、接口字段可保留英文。
- 本文件本身使用中文；不在常规变更轮次中改写为英文。
