# T02 - INTERFACE_CONTRACT

## 1. 定位

- 本文件是 `t02_junction_anchor` 的稳定契约面。
- 当前只固化阶段一 `DriveZone / has_evd gate` 的接口基线。
- 阶段二 anchoring 相关接口目前只保留占位，不在本文件中提前补完。

## 2. 模块目标与范围

- 模块目标：面向双向 Segment 相关路口锚定建立下游处理模块。
- 当前正式范围：
  - 消费 T01 上游 `segment` 与 `nodes`
  - 结合 `DriveZone.geojson` 做资料存在性 gate
  - 产出 `nodes.has_evd`、`segment.has_evd`、`summary` 与审计留痕
- 当前不在正式范围：
  - 最终锚定结果
  - 锚定几何表达
  - 候选生成机制
  - 概率 / 置信度实现

## 3. Inputs

### 3.1 阶段一必选输入

- `segment`
- `nodes`
- `DriveZone.geojson`

### 3.2 阶段一依赖字段：当前业务基线口径

#### `segment`

- `id`
- `pair_nodes`
- `junc_nodes`
- `s_grade` 逻辑字段
- 稳定 `segment` 标识字段，用于审计追溯

#### `nodes`

- `id`
- `mainnodeid`
- 节点几何

#### `DriveZone.geojson`

- 多边形或等价面状范围几何
- 需可用于“落入或边界接触”判定

### 3.3 与 T01 当前正式文档的对表说明

- `segment` 实际输入字段冻结为：
  - `id`
  - `pair_nodes`
  - `junc_nodes`
- `nodes` 实际输入字段冻结为：
  - `id`
  - `mainnodeid`
- 文档中仍可使用“mainnode”作为业务概念名，但 stage1 实际读取字段是 `mainnodeid`。
- `working_mainnodeid` 不作为 stage1 正式输入字段。
- `s_grade` 的 stage1 逻辑字段允许兼容读取：
  - `s_grade`
  - `sgrade`
- 两者不会同时出现。
- 该兼容映射用于 T02 读取输入，不代表要求 T01 修改历史产物。

### 3.4 输入前提

- `segment` 与 `nodes` 必须来自同一轮、可相互追溯的 T01 上游事实。
- `DriveZone.geojson` 必须代表“有资料区域”的稳定路面范围。
- `nodes` 与 `DriveZone` 在做空间关系判断前，必须统一到 `EPSG:3857`。
- 若 CRS 不可判定或不可对齐，应显式失败；本轮不定义缺失 CRS 的修复策略。

## 4. Stage1 Processing Contract

### 4.1 路口来源

- 仅处理每个 `segment` 的：
  - `pair_nodes`
  - `junc_nodes`
- 对单个 `segment`，先对 `pair_nodes + junc_nodes` 去重，再进入判定。
- 若去重后 `pair_nodes + junc_nodes` 为空：
  - `segment.has_evd = no`
  - 必须留审计
  - `reason = no_target_junctions`

### 4.2 路口组装规则

对每个路口 ID：

1. 对目标 `junction_id = J`，查找 `mainnodeid = J` 的 node 组。
2. 若未找到，再查 `mainnodeid = NULL` 且 `id = J` 的单点。
3. 若两者都不存在，则该路口记为 `has_evd = no`，并写审计原因 `junction_nodes_not_found`。

### 4.3 代表 node 写值规则

- 正常场景：
  - 对目标 `junction_id = J`
  - 若按 `mainnodeid = J` 找到一组 node
  - 则组内 `id = J` 的 node 为代表 node
- 单点兜底：
  - 若该组来自 `mainnodeid = NULL` 且 `id = J` 的单点
  - 则该单点为代表 node
- 其它从属 node：保持 `null`
- 若 `mainnodeid = J` 的组存在，但组内不存在 `id = J` 的 node：
  - 不能 silent skip
  - 需作为异常留痕记录
  - 不擅自创造新的普适 fallback 规则
- 环岛场景：
  - 当前阶段不由 T02 stage1 自行重定义代表 node 规则
  - 暂按 T01 既有逻辑 / 既有语义继承处理
  - 这是上游继承约束，不代表 T02 已形成独立闭环

### 4.4 `DriveZone` 判定规则

- 对路口组内所有 node 做空间判定。
- 任一 node 落入 `DriveZone` 或与 `DriveZone` 边界接触，即该路口 `has_evd = yes`。
- 否则该路口 `has_evd = no`。
- 当前阶段允许误伤，不做误伤捞回。

## 5. Outputs

### 5.1 `nodes.has_evd`

- 在 `nodes` 全表新增 `has_evd` 字段。
- 业务值域：
  - `yes`
  - `no`
  - `null`
- 只有路口代表 node 写 `yes/no`。
- 非代表 node 保持 `null`，不写重复值。

### 5.2 `segment.has_evd`

- 在 `segment` 图层新增 `has_evd` 字段。
- 规则：
  - 去重后的相关路口全部为 `yes` 时，`segment.has_evd = yes`
  - 否则 `segment.has_evd = no`

### 5.3 `summary`

- 按 `s_grade` 分桶独立统计。
- 当前阶段一只认：
  - `0-0双`
  - `0-1双`
  - `0-2双`
- 每个桶至少统计：
  - `segment_count`
  - `junction_count`
  - `junction_has_evd_count`
  - `segment_has_evd_count`

统计口径：

- 桶内路口按唯一路口 ID 计数。
- 不按 Segment 展开重复计数同一桶内重复路口。
- 同一路口可在不同桶中分别计数。

说明：

- 早期讨论曾误写为下划线版本。
- 当前正式冻结为与 T01 一致的连字符写法。

### 5.4 审计留痕

- 阶段一必须保留可追溯审计结果。
- 审计记录至少应包含：
  - `segment` 标识
  - 路口 ID
  - 路口来源：`pair_nodes` / `junc_nodes`
  - 组装路径：`mainnode_group` / `single_node_fallback` / `not_found`
  - 代表 node 解析状态
  - `has_evd` 结果
  - `reason`

## 6. 异常 / 失败口径

- `no_target_junctions`：
  - 业务结果记为 `segment.has_evd = no`
  - 必须落审计
- `junction_nodes_not_found`：
  - 业务结果记为 `no`
  - 必须落审计
  - 不允许 silent skip
- 代表 node 缺失：
  - 不能 silent skip
  - 必须留异常审计
  - 当前不定义新的普适 fallback 规则
- 必需输入缺失、必需字段缺失、CRS 不可用：
  - 视为执行失败
  - 不得伪装成业务 `no`
- 当前未定义对异常的自动修复或 silent fallback。

## 7. 待阶段二确认的接口项

- 锚定结果字段与文件形态
- 锚定几何表达
- 候选集合与候选审计结构
- 概率 / 置信度输出字段
- 阶段二失败分类

本文件不提前补充上述接口。

## 8. Acceptance

1. 阶段一输入、输出、统计与审计口径可从本文件直接追溯。
2. `has_evd` 明确保持 `yes/no/null` 业务语义。
3. `segment.has_evd` 明确是严格全满足规则。
4. stage1 实际输入字段、`s_grade` 兼容映射、代表 node 规则与 `EPSG:3857` 口径已冻结。
