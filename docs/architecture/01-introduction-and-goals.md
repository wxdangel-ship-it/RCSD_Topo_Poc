# 01 引言与目标

## 状态

- 当前状态：项目级架构摘要说明
- 来源依据：
  - `SPEC.md`
  - `docs/PROJECT_BRIEF.md`
- 审核重点：
  - 确认当前阶段是否只落骨架与治理基线
  - 确认未误引入 Highway 业务正文

## 系统目标

`RCSD_Topo_Poc` 当前目标是建立并维护一套适用于 RCSD 场景拓扑类能力的工程底座，使已登记模块和后续模块启动、治理、实现、审计都有统一起点。

## 业务目标

当前业务目标不是冻结 RCSD 模块列表，而是先保证：

- 可初始化
- 可治理
- 可扩展
- 可审计
- 可在双环境约束下传递结构化文本诊断信息

## 文档目标

当前文档治理目标是：

- 明确项目级与模块级 source-of-truth 分层
- 把 `AGENTS.md` 约束在 durable guidance
- 把标准 Skill 统一收口到 repo root `.agents/skills/`
- 为未来任何 RCSD 模块提供统一启动模板

## 范围说明

当前项目级正式口径为：

- 当前已登记正式业务模块：`t01_data_preprocess`、`t02_junction_anchor`
- 当前已纳入治理的工具集合模块：`t00_utility_toolbox`
- `modules/_template/` 是模板目录，不属于业务模块
- 当前共享代码除文本回传协议与基础 CLI 外，也承接已登记模块的实现入口
