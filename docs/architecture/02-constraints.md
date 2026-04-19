# 02 约束

## 状态

- 当前状态：项目级约束说明
- 来源依据：
  - `SPEC.md`
  - `docs/ARTIFACT_PROTOCOL.md`
  - `AGENTS.md`

## 全局约束

- 当前阶段禁止迁移 Highway 业务模块实现。
- 当前阶段禁止无任务书、无登记地扩展新的 RCSD 业务模块。
- 当前输入数据组织方式先保持与 `Highway_Topo_Poc` 一致。
- 涉及 GIS / 拓扑 / 空间数据处理的设计与编码，必须按高质量 GIS 算法工程标准执行：
  - 优先保证 CRS 与坐标变换正确性。
  - 优先保证拓扑关系、几何语义与输入契约一致。
  - 结果必须可解释、可审计、可复现。
  - 性能问题必须可测量、可定位、可验证。
  - 禁止 silent fix、黑箱规则或未声明的几何假设。
  - 禁止根据局部样本、人工真值或单次冒烟结果，自行反推上游字段语义并直接写成强规则。
  - 若样本现象与已确认语义冲突，必须先做数据分析并与用户确认，再调整规则或契约。
- 输入字段治理约束：
  - 未在项目 / 模块源事实文档中正式启用的字段，不得直接进入 Step1 / Step2 强规则。
  - `Road.formway` 已正式启用；当前已确认可用于道路形态语义判断与 through incident degree 的裁剪。
  - `formway` 具体启用位语义，必须在模块契约中明确登记；未确认位不得自行扩展为强规则。
- 文档与实现必须分离：
  - 文档在 `modules/<module>/`
  - 实现在 `src/rcsd_topo_poc/modules/<module>/`
- 标准 Skill 统一放 repo root `.agents/skills/`，模块根目录不放 `SKILL.md`。
- `outputs/`、`outputs/_work/`、临时审计工件、`.claude/worktrees/`、`.venv/` 不属于 source-of-truth。

## 协作约束

- 项目内文档默认使用中文撰写。
- 中等及以上结构化治理变更优先走 spec-kit。
- 默认禁止新增新的执行入口脚本；新增前必须登记。

## 运行约束

- 内网与外网默认执行环境均为 WSL。
- 当前盘符映射约定：
  - 内网工作盘默认 `D:`，WSL 路径根为 `/mnt/d`
  - 外网本地工作盘默认 `E:`，WSL 路径根为 `/mnt/e`
  - 未获得用户明确更正前，不得混用或反向假设内外网盘符
- 当前测试数据根目录约定：
  - 默认测试数据根统一为 `TestData/POC_Data`
  - 内网默认数据路径根为 `/mnt/d/TestData/POC_Data`
  - 外网本地默认数据路径根为 `/mnt/e/TestData/POC_Data`
  - 未获得用户明确更正前，不得省略 `TestData` 目录或改写为 `Data/POC_Data`
- 执行边界默认划分为：
  - 外网验证、外网数据检查与当前本地工作区操作由 Agent 执行。
  - 内网环境、内网数据获取与内网命令执行由用户执行。
  - 未显式获得内网访问能力前，Agent 不得声称自己已经完成任何内网操作。
- 项目工作目录默认使用 WSL 路径，例如 `/mnt/e/Work/RCSD_Topo_Poc`。
- 若收到 Windows 路径输入，应先转换为对应的 WSL 路径再继续。
- 当前仓库本地标准环境固定为 repo root `.venv`：
  - 依赖真相固定为 `pyproject.toml` + `uv.lock`
  - Python 版本固定为 `3.10.x`
  - 本地同步命令固定为 `uv sync --python 3.10 --extra dev`
  - repo-level CLI 固定执行口径为 `.venv/bin/python -m rcsd_topo_poc <subcommand>`
  - root `scripts/` 下 Python 入口固定执行口径为 `.venv/bin/python scripts/<script>.py`
  - 测试固定执行口径为 `.venv/bin/python -m pytest ...`
  - 未经批准，不再把裸 `python`、裸 `python3` 或任意系统解释器写成官方模块契约命令
  - 在当前 T03 专门治理轮次完成前，repo-level `make test` / `make smoke` 默认只覆盖 repo 级、T00、T01、T02 测试树；T03 测试与修复单独执行
- 新增或变更本地依赖、Python 版本、执行入口时，必须在同一轮内同步完成：
  - `pyproject.toml`
  - `uv.lock`
  - repo root `Makefile`
  - `.venv/bin/python -m rcsd_topo_poc doctor` 对应审计逻辑
  - `docs/repository-metadata/code-boundaries-and-entrypoints.md`
  - `docs/repository-metadata/entrypoint-registry.md`
  - 受影响模块的 `README.md` 与 `INTERFACE_CONTRACT.md`
- 运行输出目录写入 `outputs/_work/`。
- 文本回传必须符合 `TEXT_QC_BUNDLE` 粘贴性约束。
