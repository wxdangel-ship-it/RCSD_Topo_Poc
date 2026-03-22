# T02 初始需求基线落仓记录

## 1. 背景

- 本轮任务目标是把 T02 模块的需求基线文档写入仓库。
- 当前任务性质是“文档落仓任务”，不是编码任务、实现任务或实验任务。
- 当前重点是把已收敛的 T02 业务基线写对、写稳、写清楚。

## 2. 本轮落仓范围

- 建立 `specs/t02-junction-anchor/` 下的：
  - `spec.md`
  - `plan.md`
  - `tasks.md`
- 建立 `modules/t02_junction_anchor/` 下的：
  - `AGENTS.md`
  - `INTERFACE_CONTRACT.md`
  - `README.md`
  - `architecture/overview.md`
  - `history/000-bootstrap.md`

## 3. 为什么本轮只固化 Stage1

- Stage1 的业务目标已经收敛为“DriveZone / has_evd gate”。
- Stage2 的最终锚定、候选机制、几何表达、概率 / 置信度实现目前都未冻结。
- 若在当前阶段提前补写 Stage2 细节，会把待确认内容误写成稳定契约。

## 4. 本轮有意延后的内容

- Stage2 锚定主逻辑
- 锚定结果字段
- 锚定几何表达
- 候选生成机制
- 概率 / 置信度实现
- 误伤捞回机制

## 5. 本轮读取到的上游事实

- T01 当前正式文档已明确：
  - 上游存在 `segment` 与 `nodes` 事实面
  - `segment` 侧包含 `pair_nodes`、`junc_nodes`
  - `mainnodeid = NULL` 的 node 仍是合法语义路口
- T01 当前正式文档同时显示：
  - 其正式字段名以 `id / mainnodeid / working_mainnodeid / sgrade` 为主

## 6. 本轮发现的 T01 歧义点

- `pair_nodes` 历史示例尾缀出现过 `_N` 与 `_1` 两种写法，但“表示 Segment 两端语义路口”的核心语义一致。
- 环岛代表 node 规则当前仍由 T01 既有逻辑继承，T02 尚未形成独立闭环。
- 缺失 CRS 的修复策略当前未冻结，需依赖上游数据质量或后续任务书明确。

## 7. 本轮结论

- T02 已完成需求基线文档落仓。
- 当前正式范围只到 Stage1 gate。
- stage1 实际输入字段冻结为：
  - `segment.id / pair_nodes / junc_nodes`
  - `nodes.id / mainnodeid`
- `s_grade` 逻辑字段兼容读取 `s_grade / sgrade`，正式分桶值冻结为 `0-0双 / 0-1双 / 0-2双`。
- 代表 node 规则冻结为：
  - 正常场景按 `id = junction_id`
  - 环岛当前继承 T01 逻辑
- 空目标路口 `segment` 明确记为 `has_evd = no` 且 `reason = no_target_junctions`。
- 空间判定统一在 `EPSG:3857` 下进行。
- T01 歧义已在 T02 文档中记录，但未改动 T01 文档。
- 本轮后已可进入 stage1 编码任务书准备。
