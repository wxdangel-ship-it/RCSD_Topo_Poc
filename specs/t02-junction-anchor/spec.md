# T02 路口锚定模块规格

> 本文件是 T02 需求基线的变更工件。当前正式模块长期真相以 `modules/t02_junction_anchor/architecture/*` 与 `modules/t02_junction_anchor/INTERFACE_CONTRACT.md` 为准。

## 1. 文档定位

- 文档类型：需求基线规格
- 模块 ID：`t02_junction_anchor`
- 当前状态：`baseline change artifact / completed`
- 本文件作用：保留 T02 早期需求冻结轨迹，并同步记录后续经批准的文档口径收敛；它不替代当前正式模块文档面

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
- `DriveZone`，表示所有有资料区域的路面范围；当前输入兼容 `GeoPackage(.gpkg)`、`GeoJSON` 与 `Shapefile`，历史 `.gpkt` 后缀仅做兼容读取；同名时优先 `GeoPackage`

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

在步骤1“目标语义路口确定”中，进一步冻结以下口径：

- `semantic_junction_set` 指当前语义路口的 node 集合，不是单个点。
- `mainnode` 只是该语义路口集合的代表 node，用于写值、索引和审计，不等于整个语义路口。
- 若按 `mainnodeid = J` 找到多节点语义组，则后续合法 polygon 必须一次性直接覆盖组内全部 node；若最终 polygon 不能一次性直接覆盖整组所有 node，则该 case 属于问题 case，不是合法变体。
- `boundary roads / arms` 保留为语义边界概念，但 road 的“两端”不是只看当前 road 记录的直接两端，而是要沿可穿越的 `degree=2` 过渡节点继续跟踪，直到语义边界；因此 road 的“两端”应理解为经过两度链接跟踪后的边界端点。
- `foreign boundary roads` 仅指：某条 road 经过两度链接跟踪后的两个边界端点都不属于当前 `semantic_junction_set`。
- 判断“是否误包其他语义路口”，不能只看 foreign node；若 polygon 把别的语义路口向外延伸到其他路口的 roads / arms 纳入当前路口面，即使没有直接覆盖 foreign node，也视为错误。
- 本步骤不再定义 `connector road` 术语。

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
- `RCSDIntersection`
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

- 阶段二使用 `RCSDIntersection` 做路口面判定。
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
- GeoPackage(.gpkg)
    - 审计表
- 错误态 2：`node_error_2`
  - 反向从 `RCSDIntersection` 面包含选择 node 时，若一个面对应不止一组 node
  - 则这些组对应代表 node 的 `is_anchor = fail2`
  - 同时输出到 `node_error_2`
  - `node_error_2` 需要同时保留：
- GeoPackage(.gpkg)
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
- Stage3 步骤2「模板分类」当前按以下业务口径冻结：
  - `kind_2` 在步骤2中作为强输入使用，不再只是弱证据
  - `kind_2 = 2048` 时，当前 case 直接按 `single_sided_t_mouth` 理解，不再按中心型路口模板理解
  - `kind_2 = 4` 时，当前 case 先按 `center_junction` 理解，允许后续按中心型路口铺满当前语义路口
  - 但若后续发现 foreign boundary roads、其他语义路口 roads / arms 入侵，或其它边界冲突，则该 case 仍属于问题 case
- Stage3 步骤3「目标 corridor / 口门边界」当前按以下业务口径冻结：
  - 本轮冻结为规则 A / B / C / D / E / F / G / H，不再保留旧 `10m` 正式口径
  - 步骤3只定义后续 polygon 唯一合法的活动空间，不直接生成 polygon
  - 合法活动空间只能在当前模板允许占用的 `DriveZone` 内合法道路面中生长
  - 对与当前语义路口直接连通的其他语义路口，应沿进入该语义路口的道路方向，在其入口边界前 `1m` 设置垂直于道路方向的负向掩膜边界
  - 对与当前语义路口无关、但位于同一道路面内的 foreign road / arm / node，优先沿 foreign road / arm 构造 `1m` 缓冲负向掩膜；仅在无法识别 road / arm 时，才退化为 node 周边小范围负向掩膜
  - 对道路面内、属于同一其他语义路口的 node，先按平面位置构造 MST 最小连通线集，MST 连线只保留道路面内部分，并对道路面内部分做 `1m` 缓冲负向掩膜
  - `single_sided_t_mouth` 只能在目标单侧 lane corridor 内展开，不得跨到对向 lane 或对向主路 corridor
  - 当前 case 的 Step3 `allowed space / polygon-support space` 不得进入其他语义路口，也不得纳入其他语义路口向外延伸的 `roads / arms / lane corridor`
  - 当前 case 的 Step3 `allowed space` 不得进入与当前语义/拓扑不连通的对向道路面
  - `single_sided_t_mouth` 下，对向 Road / 对向语义 Node / 对向 lane / 对向主路 corridor 一律按硬排除处理
  - 当前 case 的 Step3 候选空间必须先自成立；若某个方向只能依赖 cleanup / trim 才能不越界，则该方向的 Step3 候选空间不成立
  - 任何长度放大、mouth 补长、或竖向补长，都只能排在上述硬排除之后且在 Step3 候选空间已自成立后才允许讨论，不能先放大再依赖 cleanup / trim 做越界补救
  - `center_junction` 可先按中心型路口铺满当前 case 的合法道路面，但若后续发现 foreign boundary roads、其他语义路口 roads / arms 入侵，或其它边界冲突，则该 case 仍属于问题 case
  - 若某个方向上不存在更早的语义边界或 foreign 边界，则该方向单向最大增长距离不超过 `50m`
  - `50m` 只用于“无更早边界时”的单向补足，不替代其他边界判断，也不得突破 foreign 硬边界，更不得压过“整组 node 一次性直接覆盖”要求；旧 `10m` 正式口径取消
- Stage3 步骤4「RCSD 关联语义」当前按以下业务口径冻结：
  - 步骤4只负责在步骤2模板和步骤3合法活动空间已冻结的前提下，识别当前 case 的 `required RC`、`support RC` 与 `excluded RC`
  - A 类：`RCSD` 也构成语义路口；`RCSDNode` 按 `mainnodeid` 聚组，单节点时其“3 个方向”按“经过 `degree=2` 跟踪后的边界方向簇数”判定
  - B 类：`RCSD` 不构成语义路口，但存在相关 `RCSDRoad`；当前只要求覆盖挂接区域，而不是整条 `RCSDRoad`
  - C 类：无相关 `RCSDRoad`；不追加 `RC` 侧 required semantics
  - 步骤4可以增加“必须纳入的 `RC` 语义对象”，但不能扩大步骤3已经冻结的合法活动空间；若 `required RC` 落在步骤3合法空间之外，当前仅记为审计异常 / `stage3_rc_gap`
- Stage3 步骤5「foreign SWSD / RCSD 排除规则」当前按以下业务口径冻结：
  - 步骤5只定义哪些外部 `SWSD / RCSD` 元素一旦被纳入当前 case，就必须视为 `foreign / 错误对象`
  - foreign 对象分为三类：`foreign_semantic_nodes`、`foreign_roads_arms_corridors`、`foreign_rc_context`
  - `single_sided_t_mouth` 下，对向 lane / 对向主路 corridor / 非目标 mouth 的另一侧 corridor / 远端 `RC tail` 一律按 `foreign` 处理
  - `center_junction` 下，其他语义路口外延 `roads / arms / lane corridor`、`foreign boundary roads`、以及只在 foreign 语义上下文里成立的 `RC` 对象，只要进入当前 case 即视为错误
  - 步骤4中的 `excluded RC` 在步骤5中直接等价于 `foreign RC`
  - 单纯边界接触不算错；形成可活动、可占用、可依赖的“实际纳入”一律算错
- Stage3 步骤6「几何生成与后处理」当前按以下业务口径冻结：
  - 步骤6是受约束的几何生成步骤，不是补面或补救步骤
  - 硬约束优先级固定为：先守步骤3合法活动空间，再守步骤5 `foreign` 硬排除，再满足步骤1 must-cover，再满足步骤4 `required RC` must-cover，最后才允许做几何优化
  - `single_sided_t_mouth` 的理想几何是围绕目标单侧 mouth 的单侧口门面；`center_junction` 的理想几何是围绕当前语义中心展开的中心型路口面
  - 无意义狭长面、无意义空洞、无意义凹陷、细脖子、非当前方向远端尾巴、依赖 `foreign` 空间的补丁连接，均属于步骤6问题几何
  - geometry cleanup 只能收敛已成立的几何，不能作为让 Step3 候选空间成立的主通路，不能越出步骤3合法活动空间、不能重新引入步骤5 `foreign`、不能用 `support` 替代 `required`，也不能把问题几何“化妆成成功几何”
  - 若步骤6无法生成一个同时满足步骤1 / 步骤3 / 步骤4 / 步骤5约束、并且符合当前模板认知形态的 polygon，则该 case 在业务上应视为“路口面几何未成立”
  - 步骤6失败按两层归因冻结为：一级 `infeasible_under_frozen_constraints / geometry_solver_failed`；二级 `step1_step3_conflict / stage3_rc_gap / foreign_exclusion_conflict / template_misfit / geometry_closure_failure / cleanup_overtrim / cleanup_undertrim / foreign_reintroduced_by_cleanup / shape_artifact_failure`
  - 当前目视检查中唯一已明确确认的失败锚点是 `520394575`；除它之外，若其他 case 要进入步骤6失败归类，必须先完成根因分型
- Stage3 步骤7「准出判定」当前按以下业务口径冻结：
  - 步骤7是最终裁决层，只基于步骤1到步骤6已冻结结果做 `accepted / review_required / rejected` 分类，不承担补救职责
  - `accepted` 的最小前提是：步骤1 must-cover 成立、步骤3合法活动空间成立、步骤4 `required RC` 成立、步骤5 `foreign` 排除成立、步骤6几何成立且不是问题几何、且不存在未消除的核心审计异常
  - `review_required` 只适用于：当前结果已经满足业务需求，但几何表现、可审查性或视觉质量仍存在风险；`review_required` 只允许映射到 `V2`
  - `rejected` 只适用于：当前 case 已明确违反硬规则、或在当前冻结约束下无合法解、或步骤6已经确认“路口面几何未成立”且失败根因已明确；`rejected` 只允许映射到 `V3 / V4 / V5`
  - 步骤7不能洗白前面步骤的失败；若步骤6已认定“路口面几何未成立”，步骤7只能在 `review_required / rejected` 之间分类，不能再解释成成功
  - Stage3 结果类型与目视分类的正式映射冻结为：
    - `accepted -> V1`
    - `review_required -> V2`
    - `rejected -> V3 / V4 / V5`
  - 当前 `520394575` 作为唯一已明确确认的失败锚点保留；除它之外的其他 case 若要进入 `review_required / rejected`，必须先完成根因分析并说明属于“上游冻结约束下无合法解”还是“合法解存在但步骤6没求出来”
- Stage3 / Stage4 目视检查 PNG 当前按统一三态样式冻结：
  - `accepted`：正常成功图样式
  - `review_required`：浅琥珀 / 橙黄色系整图掩膜、深橙粗边框、风险区域橙色强调、显式 `REVIEW / 待复核` 标识
  - `rejected` 或 `success = false`：淡红整图掩膜、深红粗边框、失败区域深红强调、显式 `REJECTED / 失败` 标识
  - `review_required` 不使用红色系主样式；`V2` 必须使用该风险样式；`V3 / V4 / V5` 必须统一使用失败样式
  - 非成功图必须与成功图一眼可区分，且风险态与失败态彼此也必须一眼可区分
- 阶段一正式输入为 `segment`、`nodes`、`DriveZone`。
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
- 阶段二新增输入为 `RCSDIntersection`。
- 阶段二当前定位冻结为 anchor recognition / anchor existence，而不是最终概率型锚定闭环。
- `nodes.is_anchor` 只对代表 node 写值，枚举冻结为 `yes / no / fail1 / fail2 / null`。
- 阶段二仅处理 `has_evd = yes` 的路口组；其它组 `is_anchor = null`。
- `node_error_1 -> fail1`，`node_error_2 -> fail2`，且 `fail2` 优先于 `fail1`。
- 阶段二边界接触算成功，空间判定同样统一到 `EPSG:3857`。
- 阶段二当前不涉及成果概率 / 置信度实现。
- 已新增单 `mainnodeid` 文本证据包能力，用于局部裁剪 `nodes / roads / DriveZone / RCSDRoad / RCSDNode` 并导出单个 txt。
- 文本证据包只服务于外网实验复现，不替代正式产线输入。
- 文本证据包默认逻辑内容至少包含 `manifest.json`、`drivezone_mask.png`、`drivezone.gpkg`、`nodes.gpkg`、`roads.gpkg`、`rcsdroad.gpkg`、`rcsdnode.gpkg`、`size_report.json`。
- 文本证据包固定采用“压缩归档 + 文本编码”方案，最终体积必须 `<= 300KB`；超限时必须失败并输出体积分析报告。

### 7.1 最终成果路口面输出补充约束

- 以下图层都视为“最终成果路口面”：
  - stage3 单 case：`virtual_intersection_polygon.gpkg`
  - stage3 full-input / batch：`virtual_intersection_polygons.gpkg`
  - stage4 单 case：`stage4_virtual_polygon.gpkg`
  - stage4 batch / 全量：`stage4_virtual_polygons.gpkg`
- 所有最终成果路口面都必须包含字段：
  - `mainnodeid`
  - `kind`
- `mainnodeid` 写值规则冻结为：
  - 优先写当前 case 代表 node 的 `nodes.mainnodeid`
  - 若 `nodes.mainnodeid` 为空、缺失或不可用，则回退写当前代表 node 的 `nodes.id`
- `kind` 写值规则冻结为：
  - 优先写当前 case 代表 node 的 `nodes.kind`
  - 若 `nodes.kind` 为空、缺失或不可用，则回退写当前代表 node 的 `nodes.kind_2`
  - 若 `nodes.kind / nodes.kind_2` 同时为空、缺失或不可用，则该 case 视为缺失最终成果字段，不得静默补值
- 所有最终成果路口面 geometry 必须统一写为 `EPSG:3857`。
- 只要存在 full-input / batch / 全量运行，就必须同步输出该批次的最终全量路口面汇总图层；不得只保留单 case 目录产物而缺失汇总成果。
- 当前 Stage3 唯一正式验收基线冻结为 `E:\TestData\POC_Data\T02\Anchor`（WSL：`/mnt/e/TestData/POC_Data/T02/Anchor`）下的 `61` 个 case-package。
- 当前 `test_virtual_intersection_full_input_poc.py` 与 full-input 运行链仅承担 fixture / dev-only / regression 角色，不得再表述为 Stage3 正式交付基线。
- 当前成果审计固定采用双线模板：
  - 机器审计给根因层（`step3 / step4 / step5 / step6 / frozen-constraints conflict`）
  - 人工目视审计给快速分类（`V1 / V2 / V3 / V4 / V5`）
- Stage4 当前复用同一套成果审计与目视复核模板。

### 7.2 Stage4 正式需求文档修订同步（2026-04）

- 本轮同步属于正式需求文档修订，不属于代码重构、算法重构、测试改写或 CLI 调整。
- Stage4 当前正式契约以以下文档为准：
  - `modules/t02_junction_anchor/INTERFACE_CONTRACT.md`
  - `modules/t02_junction_anchor/architecture/06-accepted-baseline.md`
- 本轮同步冻结了 Stage4 的四类正式口径：
  - 顶层定位、处理对象与非目标
  - 七步正式业务定义
  - 正式复用 Stage3 的成果审计 / 目视复核模板
  - 最终成果路口面属性字段规则
- Stage4 复用 Stage3 的边界是：
  - 复用表达方式、审查模板和 PNG 三态样式
  - 不继承 Stage3 的业务语义，不把 Stage3 的事件解释或几何规则直接平移为 Stage4 规则
- Stage4 当前版本仍是独立补充阶段：
  - 不写回 `nodes.is_anchor`
  - 不并入统一锚定结果
  - 不承担最终唯一锚定闭环
- 当算法收敛到认可水平后，Stage4 可与 Stage3 合并进入同一锚定流程；该未来方向已在正式契约中冻结为“可合并方向”，但本轮文档修订不等于已经进入代码合并或流程合并。

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

- 当前已冻结 `node_error_1` 与 `node_error_2` 必须同时保留 GeoPackage(.gpkg) 与审计表。
- 具体文件命名、最小字段集与稳定落盘形态，待后续实现任务书确认。

## 9. 进入编码前的门禁

- 先完成本规格、模块契约与 README 的一致性复核。
- 本轮后，stage1 汇总补丁与 stage2 anchor recognition 文档基线已可进入对应实现任务书准备。
- 未经用户明确允许，不进入阶段二。
- 未经用户明确允许，不定义概率 / 置信度实现。
- 未明确失败留痕对象与最小审计字段前，不进入阶段一实现。
