# t02_junction_anchor - AGENTS

## 开工前先读

- 先读 `architecture/01-introduction-and-goals.md`、`architecture/02-constraints.md`、`architecture/04-solution-strategy.md`、`architecture/10-quality-requirements.md`。
- 再读 `INTERFACE_CONTRACT.md`，确认稳定输入、输出、入口、参数类别和验收标准。
- 若需要操作者入口，再读 `README.md`。
- 若需要历史背景，再读 `history/*`。

## 允许改动范围

- 默认可改：
  - `architecture/*`
  - `INTERFACE_CONTRACT.md`
  - `AGENTS.md`
  - `README.md`
  - `history/*`
  - `src/rcsd_topo_poc/modules/t02_junction_anchor/*`
  - `tests/modules/t02_junction_anchor/*`
- 若无明确任务，不修改：
  - T01 文档
  - stage2 相关实现
  - 概率 / 置信度定义
  - 无关公共工具逻辑

## 必做验证

- 改文档前后对照 repo root `AGENTS.md`、`SPEC.md`、项目级治理文档，避免口径冲突。
- 改 `INTERFACE_CONTRACT.md` 时，必须回看当前 CLI 入口、实现文件和关键测试，确保入口、输出与参数类别没有写错。
- 触碰 stage1 实现时，至少执行：
  - 相关 pytest
  - `git diff --check`

## 必守边界

- 当前正式实现范围只到 stage1 `DriveZone / has_evd gate`。
- stage2 当前只冻结 anchor recognition / anchor existence 的文档基线，不代表已经进入实现。
- stage2 锚定主逻辑、最终唯一锚定决策、概率 / 置信度、误伤捞回、环岛新规则都不在当前正式实现范围。
- `mainnode` 可作为业务概念名，但 stage1 正式输入字段只能是 `mainnodeid`。
- `working_mainnodeid` 不得作为 stage1 正式输入字段写回契约或强规则。
- `s_grade` 逻辑字段只允许显式兼容 `s_grade / sgrade`。
- `has_evd` 必须保持 `yes/no/null` 业务语义。
- stage1 `summary` 除 `0-0双 / 0-1双 / 0-2双` 外，还必须补充 `all__d_sgrade`。
- stage2 只处理 `has_evd = yes` 的路口组；其它组 `is_anchor = null`。
- `is_anchor` 只允许 `yes / no / fail1 / fail2 / null`。
- `node_error_1 -> fail1`，`node_error_2 -> fail2`，且 `fail2` 优先于 `fail1`。
- 不允许 silent skip；异常必须留痕。
- 未经用户明确允许，不修改 T01 文档。

## 相邻模块关系

- T01 是 T02 的上游事实源之一，当前提供 `segment` 与 `nodes`。
- T02 当前是 T01 之后的 gate + anchor recognition 基线模块，不承担最终概率型锚定决策。
- 若发现 T01 文档、T02 契约与现实现有冲突，先停下并汇报，再决定如何调整。
