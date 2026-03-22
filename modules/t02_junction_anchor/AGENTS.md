# T02 - AGENTS

## 1. 模块角色

- 模块 ID：`t02_junction_anchor`
- 当前状态：`requirements baseline / document-first`
- 当前轮次目标：固化 T02 需求基线文档，为后续阶段一编码任务书做准备

## 2. 开工前先读

- 先读 [spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t02-junction-anchor/spec.md)
- 再读 [INTERFACE_CONTRACT.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t02_junction_anchor/INTERFACE_CONTRACT.md)
- 再读 [overview.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t02_junction_anchor/architecture/overview.md)
- 需要上游事实时，回读 T01 的 `README.md`、`INTERFACE_CONTRACT.md`、`spec.md`

## 3. 子 Agent / CodeX 在本模块中的职责

- 当前只负责文档基线整理、对表与审计性记录。
- 不得跳过 `spec` 与 `INTERFACE_CONTRACT` 直接进入编码。
- 若上游口径不清，只能记录为待确认项，不得自行固化为强实现规则。

## 4. 允许改动范围

- 默认只改本模块文档：
  - `AGENTS.md`
  - `INTERFACE_CONTRACT.md`
  - `README.md`
  - `architecture/*`
  - `history/*`
  - `specs/t02-junction-anchor/*`
- 无明确任务，不修改 `src/`、`tests/`、`scripts/`、`tools/`。
- 未经用户明确允许，不新增运行入口。

## 5. 必守约束

- 文档优先，不得跳过 spec 直接编码。
- 未经允许不得修改 T01 文档。
- 若发现 T01 歧义，只能记录，不得擅改。
- `mainnode` 在本模块中可作为业务概念名，但 stage1 实际输入字段冻结为 `mainnodeid`。
- `working_mainnodeid` 不作为 stage1 正式输入字段。
- stage1 的 `s_grade` 逻辑字段允许兼容读取 `s_grade / sgrade`，不得把兼容映射误写成上游改造要求。
- stage1 的空间判定统一在 `EPSG:3857` 下进行。
- 阶段一与阶段二必须严格分界：
  - 阶段一：`DriveZone / has_evd gate`
  - 阶段二：锚定主逻辑
- 代表 node 规则必须按已冻结口径执行：
  - 正常场景：`id = junction_id`
  - 环岛：继承 T01 当前逻辑，不由 T02 自行重定义
- 不得擅自定义概率语义、概率公式或置信度阈值。
- 不得用 silent fix 掩盖字段歧义、节点归组歧义或统计歧义。

## 6. 阶段边界

- 当前正式范围只到阶段一需求基线。
- 阶段一只产出：
  - `nodes.has_evd`
  - `segment.has_evd`
  - `summary`
  - 审计留痕
- 空目标路口 `segment` 必须显式记为 `has_evd = no` 且留痕 `reason = no_target_junctions`。
- 阶段二只保留目标占位，不在本轮展开字段或算法。

## 7. 提交前检查

- 对照 repo root `AGENTS.md`、`SPEC.md` 与项目级治理文档，确认口径不冲突。
- 对照 T01 上游文档，确认已把歧义显式列为待确认项。
- 至少执行 `git diff --check`。
