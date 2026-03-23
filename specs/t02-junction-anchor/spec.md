# T02 路口锚定模块规格

> 本文件是 T02 stage1 初始基线的变更工件。当前正式模块长期真相以 `modules/t02_junction_anchor/architecture/*` 与 `modules/t02_junction_anchor/INTERFACE_CONTRACT.md` 为准。

## 1. 文档定位

- 文档类型：需求基线规格
- 模块 ID：`t02_junction_anchor`
- 当前状态：`baseline change artifact / completed`
- 本文件作用：保留 T02 stage1 初始需求冻结轨迹，不替代当前正式模块文档面

## 2. 模块业务定位

- T02 是 RCSD_Topo_Poc 中承接 T01 之后的下游模块。
- T01 提供双向 Segment 相关的 `segment` 与 `nodes` 上游事实；T02 在其基础上继续处理“与 Segment 相关的路口”。
- T02 的总体目标是完成双向 Segment 相关路口锚定，但当前只对阶段一形成稳定需求基线。

## 3. 与 T01 的关系

- T01 是 T02 的上游事实源之一。
- T02 当前消费的逻辑对象来自 T01：
  - `segment`
  - `nodes`
- T02 不回写、不重定义 T01 的业务语义；若发现口径冲突，只记录并上报。
- 当前 T02 stage1 的实际输入字段已按本轮确认口径冻结，并与 T01 当前实际写法保持兼容。

## 4. T02 分阶段推进

### 4.1 阶段一：DriveZone / has_evd gate

- 阶段一不是正式锚定本体。
- 阶段一目标是：对双向 Segment 相关路口做“是否有有效资料”的 gate 判定。
- 阶段一只产出资料存在性判断、汇总统计与审计留痕。

### 4.2 阶段二：锚定主逻辑

- 阶段二当前冻结的业务定位是：双向 Segment 相关路口的 anchor recognition / anchor existence。
- 阶段二不是最终概率型锚定决策闭环。
- 阶段二当前不定义成果概率 / 置信度、不定义最终锚定几何、不扩写候选生成与候选排序机制。
- 阶段二当前只冻结输入、状态枚举、错误态与阶段边界；不在本轮扩写成最终锚定算法。
- 本轮不进入阶段二实现。

## 5. 阶段一正式需求基线

### 5.1 正式输入

- `segment` 图层，来自 T01。
- `nodes` 图层，来自 T01。
- `DriveZone.geojson`，表示所有有资料区域的路面范围。

### 5.2 实际输入字段冻结

#### `segment`

- 主键字段：`id`
- 路口字段：`pair_nodes`
- 路口字段：`junc_nodes`
- `s_grade` 逻辑字段：
  - stage1 逻辑上需要读取 `s_grade`
  - 实际输入字段允许为 `s_grade` 或 `sgrade`
  - 两者不会同时出现
  - 这是输入兼容映射，不代表要求 T01 改历史产物

#### `nodes`

- 主键字段：`id`
- junction 分组字段：`mainnodeid`

说明：

- 文档中仍可使用“mainnode”作为业务概念名。
- 但 T02 stage1 的实际输入字段冻结为 `mainnodeid`。
- `working_mainnodeid` 不作为 stage1 正式输入字段。
### 5.3 路口来源范围

- 仅处理 `segment` 中以下两类路口：
  - `pair_nodes`
  - `junc_nodes`
- 不从其它字段、几何推断或人工样本额外补路口。

### 5.4 单个 Segment 内的去重规则

- 对单个 `segment`，先将 `pair_nodes + junc_nodes` 合并并去重。
- 后续该 `segment` 的阶段一资料判定，以去重后的唯一路口 ID 集合为准。

若某个 `segment` 在 stage1 中，去重后 `pair_nodes + junc_nodes` 为空：

- `segment.has_evd = no`
- 必须保留审计留痕
- `reason = no_target_junctions`

### 5.5 路口组装规则

对每个从 `segment` 提取出的路口 ID，在 `nodes` 中查找构成该路口的所有 node：

1. 对目标 `junction_id = J`，若存在 `mainnodeid = J` 的所有 node，则这些 node 构成该路口组。
2. 若不存在上述组，且存在 `mainnodeid = NULL` 且 `id = J` 的单个 node，则该单点作为该路口组。

说明：

- 以上是当前 T02 阶段一采用的业务查找规则。
- 其中“mainnode”是业务概念名；stage1 实际读取字段是 `mainnodeid`。
- 若 T01 文档存在歧义，只能记录，不得改写 T01。

### 5.6 路口代表 node 写值规则

- 正常场景：
  - 对目标 `junction_id = J`
  - 若按 `mainnodeid = J` 找到一组 node
  - 则组内 `id = J` 的 node 为代表 node
- 单点兜底场景：
  - 若该组来自 `mainnodeid = NULL` 且 `id = J` 的单点
  - 则该单点即代表 node
- 同组其它从属 node 不写值，保持空 / `null`。
- 若 `mainnodeid = J` 的组存在，但组内不存在 `id = J` 的 node：
  - 不能 silent skip
  - 需作为异常留痕记录
  - 不擅自创造新的普适 fallback 规则
- 环岛场景：
  - 当前阶段不得由 T02 stage1 自行重定义环岛代表 node 规则
  - 暂按 T01 既有逻辑 / 既有语义继承处理
  - 这是当前阶段的上游继承约束，不代表 T02 已完成独立业务闭环

### 5.7 CRS 与空间判定口径

- T02 stage1 的空间判定统一在 `EPSG:3857` 下进行。
- `nodes` 与 `DriveZone` 在进行空间关系判断前，必须统一到 `EPSG:3857`。
- 本轮不擅自扩写缺失 CRS 的修复策略。
- 若输入缺失 CRS，应列为待确认 / 依赖上游数据质量问题，不在 stage1 文档中自造修复规则。

### 5.8 DriveZone 判定规则

- 对该路口组内所有 node，判断其是否落入 `DriveZone`。
- 只要组内任一 node 落入 `DriveZone`，则该路口判定成功。
- 与 `DriveZone` 的边界接触也算成功。
- 当前阶段允许误伤，不在阶段一做捞回。

### 5.9 路口 `has_evd` 规则

- 成功：代表 node 的 `has_evd = yes`
- 失败：代表 node 的 `has_evd = no`
- 非代表 node：`has_evd = null`

`has_evd` 当前保持业务值域：

- `yes`
- `no`
- `null`

不得偷换为布尔值或 `0/1` 语义。

### 5.10 找不到路口组时的规则

若 `segment` 中存在某路口 ID，但在 `nodes` 中：

- 既找不到 `mainnodeid = 该路口 ID` 的组
- 也找不到 `mainnodeid is NULL` 且 `id = 该路口 ID` 的单点

则：

- 该路口按 `has_evd = no`
- 必须保留审计留痕
- `reason = junction_nodes_not_found`
- 不允许 silent skip

### 5.11 `segment.has_evd` 规则

- 若某个 `segment` 下所有相关路口在去重后都为 `has_evd = yes`，则 `segment.has_evd = yes`
- 否则 `segment.has_evd = no`

这是严格全满足规则，不是比例规则。

### 5.12 `summary` 统计口径

- `summary` 按 `s_grade` 分桶独立统计。
- 当前 T02 阶段一业务基线只认以下分级写法：
  - `0-0双`
  - `0-1双`
  - `0-2双`
- 每个 `s_grade` 桶至少统计：
  - 多少 Segment
  - 涉及多少路口
  - 多少路口有资料
  - 多少 Segment 有资料
- 同时补充一条新的总汇总项：
  - `all__d_sgrade`
  - 业务含义：统计所有 `s_grade` 非空的 `segment`
  - 统计项与单桶保持一致：
    - `segment_count`
    - `junction_count`
    - `junction_has_evd_count`
    - `segment_has_evd_count`

统计规则：

- 每个桶内，对“路口 ID”按唯一值计数。
- 不按 Segment 展开重复计数同一桶内重复路口。
- 同一个路口若出现在不同 `s_grade` 桶内，可分别计入对应桶。
- `all__d_sgrade` 与单桶保持同一统计口径：
  - 仅统计 `s_grade` 非空的 `segment`
  - 路口按唯一路口 ID 计数
  - 不按 `segment-路口` 展开重复计数
- 在现有 `summary_by_s_grade` 之外，并存新增 `summary_by_kind_grade`：
  - 固定 bucket：`kind2_4_64_grade2_1`、`kind2_4_64_grade2_0_2_3`、`kind2_2048`、`kind2_8_16`
  - 统计对象是阶段一目标路口全集，按 `junction_id` 唯一值计数
  - 分类依据以代表 node 的 `kind_2 / grade_2` 为准
  - 每个 bucket 至少统计：
    - `junction_count`
    - `junction_has_evd_count`
  - `kind_2 in {4, 64} and grade_2 = 1` 归入 `kind2_4_64_grade2_1`
  - `kind_2 in {4, 64} and grade_2 in {0, 2, 3}` 归入 `kind2_4_64_grade2_0_2_3`
  - `kind_2 = 2048` 归入 `kind2_2048`
  - `kind_2 in {8, 16}` 归入 `kind2_8_16`
  - 代表 node 无法确定、`kind_2 / grade_2` 缺失或不落入上述四类时，不新增正式 bucket，仅记录未分类数量提示

说明：

- 早期讨论曾误写为下划线版本。
- 当前正式冻结为与 T01 一致的连字符写法。

### 5.13 阶段一输出

- `nodes.has_evd`
- `segment.has_evd`
- `summary`
- 审计留痕

阶段一输出的本质是 gate 结果，而不是最终锚定结果。

### 5.14 审计与失败口径

- 阶段一必须对每个路口判定过程保留可追溯审计信息。
- 至少应能追溯：
  - 来源 `segment`
  - 路口 ID
  - 路口来源槽位：`pair_nodes` / `junc_nodes`
  - 路口组解析路径：`mainnode_group` / `single_node_fallback` / `not_found`
  - 代表 node 解析状态
  - 判定结果：`yes` / `no`
  - 失败或异常原因
- `reason = no_target_junctions` 与 `reason = junction_nodes_not_found` 已在 stage1 基线中冻结。
- “找不到路口组”属于业务结果中的 `no`，不是可静默跳过的成功。
- 缺失必需输入、缺失必需字段、CRS 不可判定等问题，属于执行前或执行中的显式失败，不得降格为业务 `no`。

### 5.15 阶段二输入与业务定位

- 阶段二新增输入：
  - `RCSDIntersection.geojson`
- 阶段二当前只处理 `has_evd = yes` 的路口组。
- `has_evd != yes` 的路口组不进入 stage2 anchor 判定。
- 对上述未进入 stage2 的组，`is_anchor` 保持 `null`。

### 5.16 阶段二新增字段

- `nodes` 全表新增字段：
  - `is_anchor`
- 写值规则：
  - 只对代表 node 写值
  - 同组其它从属 node 保持 `null`
  - 非代表 node 不重复写值
- `is_anchor` 允许值冻结为：
  - `yes`
  - `no`
  - `fail1`
  - `fail2`
  - `null`

### 5.17 阶段二空间判定与 anchor recognition 规则

- 阶段二使用 `RCSDIntersection.geojson` 做路口面判定。
- 与 stage1 一致，边界接触也算成功。
- 阶段二空间处理同样统一在 `EPSG:3857` 下进行。
- 本轮不扩写缺失 CRS 的修复策略。
- 对目标 `junction` 组，仅限 `has_evd = yes`：
  1. 若组内任一 node 落入或接触任一 `RCSDIntersection` 面，则代表 node 进入“命中态”，但仍需继续检查 `fail1 / fail2`
  2. 若组内所有 node 均未落入任何 `RCSDIntersection` 面，则代表 node 的 `is_anchor = no`

### 5.18 阶段二错误态、审计输出与优先级

- 错误态 1：`node_error_1`
  - 若同一组 node 落入两个不同的 `RCSDIntersection` 面
  - 则该组代表 node 的 `is_anchor = fail1`
  - 同时输出到 `node_error_1`
  - `node_error_1` 需要同时保留：
    - GeoJSON
    - 审计表
- 错误态 2：`node_error_2`
  - 反向从 `RCSDIntersection` 面包含选择 node 时，若一个面对应不止一组 node
  - 则这些组对应代表 node 的 `is_anchor = fail2`
  - 同时输出到 `node_error_2`
  - `node_error_2` 需要同时保留：
    - GeoJSON
    - 审计表
- `is_anchor` 业务含义冻结为：
  - `yes`：`has_evd = yes`，且该组命中且仅稳定对应一个 `RCSDIntersection` 面，未触发错误态
  - `no`：`has_evd = yes`，但未命中任何 `RCSDIntersection` 面
  - `fail1`：该组命中两个不同的 `RCSDIntersection` 面
  - `fail2`：一个 `RCSDIntersection` 面对应不止一组 node
  - `null`：非代表 node，或 `has_evd != yes` 的组
- 优先级冻结为：
  - `fail2` 优先于 `fail1`
  - 若同一组同时命中 `node_error_1` 与 `node_error_2`
  - 则代表 node 的 `is_anchor = fail2`
  - 同时仍保留相应审计输出

### 5.19 阶段二 summary 基线

- 阶段二新增 `t02_stage2_summary.json`。
- 语义冻结：
  - “资料” = `has_evd = yes`
  - “锚定” = `is_anchor = yes`
  - `fail1 / fail2 / no / null` 都不计为“被锚定”
- 阶段二按 `segment.s_grade` 输出 `anchor_summary_by_s_grade`：
  - 固定 bucket：`0-0双 / 0-1双 / 0-2双 / all__d_sgrade`
  - 每个 bucket 至少统计：
    - `total_segment_count`
    - `pair_nodes_all_anchor_segment_count`
    - `pair_and_junc_nodes_all_anchor_segment_count`
  - `pair_nodes_all_anchor_segment_count` 仅检查单个 `segment` 去重后的 `pair_nodes` 集合，集合必须非空且全部 `is_anchor = yes`
  - `pair_and_junc_nodes_all_anchor_segment_count` 检查单个 `segment` 去重后的 `pair_nodes + junc_nodes` 并集，并集必须非空且全部 `is_anchor = yes`
  - `all__d_sgrade` 统计所有 `s_grade` 非空的 `segment`
- 阶段二按代表 node.`kind_2 / grade_2` 输出 `anchor_summary_by_kind_grade`：
  - 固定 bucket：`kind2_4_64_grade2_1 / kind2_4_64_grade2_0_2_3 / kind2_2048 / kind2_8_16`
  - 每个 bucket 至少统计：
    - `evidence_junction_count`
    - `anchored_junction_count`
  - 仅统计 `has_evd = yes` 的目标路口
  - `anchored_junction_count` 仅统计 `is_anchor = yes` 的路口
  - 代表 node 无法确定、`kind_2 / grade_2` 缺失或未落入四类时，不新增正式 bucket，仅记录未分类数量提示

## 6. 当前非范围

- 不输出最终锚定结果
- 不定义锚定几何表达
- 不定义候选生成机制
- 不定义成果概率 / 置信度实现
- 不做误伤捞回
- 不做最终唯一锚定决策闭环
- 不做候选排序
- 不做候选概率校准
- 不新增环岛独立新规则
- 不扩写 stage2 之外的后续阶段算法

## 7. 当前已确认事项

- T02 总目标是双向 Segment 相关路口锚定。
- 当前采用“阶段一 gate、阶段二 anchoring”的两阶段推进。
- 当前阶段一实现基线已冻结，阶段二 anchor recognition 文档基线也已冻结。
- 阶段一正式输入为 `segment`、`nodes`、`DriveZone.geojson`。
- stage1 实际输入字段冻结为：
  - `segment.id / pair_nodes / junc_nodes`
  - `nodes.id / mainnodeid`
- 阶段一仅处理 `pair_nodes` 与 `junc_nodes`。
- `s_grade` 逻辑字段允许从 `s_grade` 或 `sgrade` 读取，两者不会同时出现。
- `nodes.has_evd` 只在路口代表 node 上写 `yes/no`，其它同组 node 保持 `null`。
- `segment.has_evd` 采用严格全满足规则。
- 空目标路口 `segment` 明确记为 `has_evd = no`，并写 `reason = no_target_junctions`。
- 空间判定统一在 `EPSG:3857` 下进行。
- `summary` 在单桶内按唯一路口 ID 统计，不做按 Segment 的重复展开计数。
- stage1 `summary` 在分桶之外补充 `all__d_sgrade` 总汇总项。
- 阶段二新增输入为 `RCSDIntersection.geojson`。
- 阶段二当前定位冻结为 anchor recognition / anchor existence，而不是最终概率型锚定闭环。
- `nodes.is_anchor` 只对代表 node 写值，枚举冻结为 `yes / no / fail1 / fail2 / null`。
- 阶段二仅处理 `has_evd = yes` 的路口组；其它组 `is_anchor = null`。
- `node_error_1 -> fail1`，`node_error_2 -> fail2`，且 `fail2` 优先于 `fail1`。
- 阶段二边界接触算成功，空间判定同样统一到 `EPSG:3857`。
- 阶段二当前不涉及成果概率 / 置信度实现。

## 8. 剩余待确认项 / 非阻断风险 / 上游依赖

### 8.1 环岛场景的后续完善空间

- 当前阶段对环岛代表 node 只承接 T01 既有逻辑 / 既有语义。
- T02 还未形成独立的环岛代表 node 闭环规则。
- 该项可在后续轮次完善，但不阻断 stage1 编码任务书准备。

### 8.2 `pair_nodes` 历史示例写法差异

- T01 正式与历史文档中，`pair_nodes` 来源语义一致，均表示 Segment 两端语义路口。
- 但历史示例曾出现两种尾缀写法：
  - `A_B_N -> A,B`
  - `A_B_1 -> A,B`
- 当前差异不影响 T02 阶段一直接消费已物化的 `pair_nodes` 字段。
- 若后续阶段需要反向依赖 `segmentid` 解析规则，必须先与 T01 正式口径再次对表。

### 8.3 CRS 缺失场景

- 当前只冻结了“空间判定统一到 `EPSG:3857`”。
- 若输入缺失 CRS，当前视为依赖上游数据质量或后续任务书明确，不在本轮自造修复策略。

### 8.4 阶段二错误输出的稳定文件命名与最小审计字段

- 当前已冻结 `node_error_1` 与 `node_error_2` 必须同时保留 GeoJSON 与审计表。
- 具体文件命名、最小字段集与稳定落盘形态，待后续实现任务书确认。

## 9. 进入编码前的门禁

- 先完成本规格、模块契约与 README 的一致性复核。
- 本轮后，stage1 汇总补丁与 stage2 anchor recognition 文档基线已可进入对应实现任务书准备。
- 未经用户明确允许，不进入阶段二。
- 未经用户明确允许，不定义概率 / 置信度实现。
- 未明确失败留痕对象与最小审计字段前，不进入阶段一实现。
