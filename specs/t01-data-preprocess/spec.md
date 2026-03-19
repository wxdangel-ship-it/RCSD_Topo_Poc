# T01 数据预处理规格草案

## 1. 文档状态

- 状态：`Draft / Step2 Segment POC`
- 当前阶段：允许编码与外网验证的原型研发阶段
- 当前用途：固化 T01 当前已确认的 Step1 / Step2 业务语义、原型边界与审查输出
- 当前限制：本文件描述的是当前 POC 口径，不是最终生产规则封板

## 2. 当前范围

- 模块名：`T01`
- 模块定位：数据预处理模块
- 当前主线能力：
  - Step1：`pair_candidates`
  - Step2：candidate validation + segment construction
- 当前验证要求：
  - 必须可输出 QGIS 可直接审查的图层
  - 必须在外网测试数据 `XXXS` 上完成实际运行验证

## 3. 已确认输入

### 3.1 Road

- 图层含义：道路数据图层
- 几何类型：`LineString`
- 文件格式：`Shp` 或 `GeoJSON`
- 当前核心字段：
  - `id`
  - `snodeid`
  - `enodeid`
  - `direction`
  - `formway`

### 3.2 Node

- 图层含义：节点数据图层
- 几何类型：`Point`
- 文件格式：`Shp` 或 `GeoJSON`
- 当前核心字段：
  - `id`
  - `kind`
  - `grade`
  - `closed_con`
  - `mainnodeid`

### 3.3 当前输入处理前提

- 输入 CRS 统一归一化到 `EPSG:3857`
- `mainnodeid` 仍是当前语义路口聚合主依据
- `direction=0/1` 当前仍按双向处理
- 未正式启用字段不得因局部样本或人工真值直接升级为强规则
- `Road.formway` 当前已正式启用，但仅限：
  - Step1：`bit7` 可用于 through incident degree 裁剪
  - Step2：`bit8` 可用于左转专用道审计 / 排除

## 4. Step1 语义

### 4.1 Step1 负责什么

- 基于 seed / terminate 规则筛选候选语义路口
- 在语义路口图上执行 BFS 搜索
- through 节点继续追溯
- A→B / B→A 双向确认

### 4.2 Step1 输出什么

- Step1 输出的是 `pair_candidates`
- 当前 `pair_candidates` 的成立条件仍是：
  - `A` 能搜索到 `B`
  - `B` 也能反向搜索到 `A`
- Step1 输出不能默认视为“最终有效 Pair”
- Step1 不负责最终 Pair 有效性确认

### 4.3 Step1 当前审查输出

- `seed_nodes.*`
- `terminate_nodes.*`
- `pair_candidates.*`
- `pair_links_candidates.*`
- `pair_candidate_nodes.*`
- `pair_support_roads.*`
- `rule_audit.json`
- `search_audit.json`
- `pair_summary.json`

说明：

- 当前仍保留 `pair_nodes.geojson` / `pair_links.geojson` / `pair_table.csv` 兼容别名
- 但语义口径以 `pair_candidates` 为准

## 5. Step2 语义

### 5.1 Step2 定位

**Step2 = pair candidate validation + segment construction**

也就是：

- Step2 不只是“从 Pair 提 Road”
- Step2 首先要验证：某个 Step1 `pair_candidate(A,B)` 是否能形成合法 Segment
- 只有通过验证的 candidate，才进入：
  - `validated_pair`
  - `trunk`
  - `segment`

### 5.2 Step2 当前 POC 流程

1. 消费 Step1 `pair_candidates`
2. 为每个 candidate 生成候选通道子图
3. 对通往其他 terminate node 的分支执行回溯裁枝
4. 在裁枝后子图上识别 trunk
5. 对 candidate 执行 validated / rejected 判定
6. 围绕 trunk 收敛完整 segment

### 5.3 候选通道

- 候选通道的起点是 Step1 支撑路径
- 在当前 POC 中，会沿支撑路径局部扩张附属分支 / 回环
- 若分支最终通往其他 terminate node，必须保留审计信息，供后续裁枝

### 5.4 分支回溯裁枝

- 若候选集合中的某条分支最终通往其他 terminate node，且该 terminate node 不是当前 Pair 的 `B`
- 则该分支不属于当前 `A-B Segment`
- 必须从附属路口处执行回溯迭代裁枝
- 裁枝痕迹必须显式输出到 `branch_cut_roads.*`

### 5.5 主干定义

- 主干不是 Segment 本身
- 当前 trunk 定义为：
  - `A→B` 与 `B→A` 构成的逆时针最小回环道路集合
- 当前左舵国家业务口径下：
  - 只有满足逆时针闭环的 trunk 才能通过验证

### 5.6 左转专用道

- 即使某条 Road 参与最小回环，若其业务属性为左转专用道，则不得直接进入 trunk
- 当前通过 `formway bit8` 识别左转专用道
- 但数据有效性可能不足，因此必须支持可配置模式：
  - `strict`
  - `audit_only`
  - `off`

### 5.7 Segment 与 trunk 的关系

- `segment != trunk`
- trunk 只是 Segment 的骨架
- 完整 Segment 是围绕 trunk 保留下来的、仍服务于当前 `A-B` 的完整通道子图

### 5.8 validated / rejected

当前 candidate 至少在以下情况下会被拒绝：

- `invalid_candidate_boundary`
- `disconnected_after_prune`
- `no_valid_trunk`
- `only_clockwise_loop`
- `left_turn_only_polluted_trunk`
- `shared_trunk_conflict`

当前 candidate 通过验证后，会输出：

- `validated_pairs.*`
- `pair_links_validated.*`
- `trunk_roads.*`
- `segment_roads.*`

## 6. 当前原型输出

### 6.1 Step1

- `pair_candidates.csv`
- `pair_links_candidates.geojson`
- `pair_candidate_nodes.geojson`
- `pair_support_roads.geojson`

### 6.2 Step2

- `validated_pairs.csv`
- `rejected_pair_candidates.csv`
- `pair_links_validated.geojson`
- `trunk_roads.geojson`
- `segment_roads.geojson`
- `branch_cut_roads.geojson`
- `pair_candidate_channel.geojson`
- `pair_validation_table.csv`
- `segment_summary.json`
- `working_graph_debug.geojson`

说明：

- 上述输出属于当前原型审查输出
- 不代表最终生产出参已经封板

## 7. 当前不纳入范围

- 多轮双向 Segment 全流程闭环
- T 型路口轮间复核完整实现
- 单向 Segment 阶段
- Step2 生产规则封板
- trunk 归属冲突的最终最优分配策略
- `formway` 通用规则引擎

## 8. 当前待确认问题

1. `only_clockwise_loop` 在实际业务上是否一律拒绝，还是后续需要引入更细的几何 / 方向复核
2. `shared_trunk_conflict` 在最终方案中是直接拒绝、延后归属，还是需要引入更稳定的 pair 排序策略
3. `formway bit8` 的数据质量是否足以从 POC 审计规则升级为生产强规则
4. 候选通道的局部扩张边界，后续是否需要引入更强的层级 / 方位 / 通道宽度约束
