# T01 - INTERFACE_CONTRACT

## 1. 文档状态

- 状态：`POC Contract Draft`
- 当前阶段：`Step1 Pair Candidate + Step2 Segment POC`
- 当前用途：固化 T01 当前原型阶段的输入、输出与审计契约
- 当前限制：下述输出契约属于原型审查输出，不是最终生产出参封板

## 2. 输入契约

### 2.1 Road

- 支持格式：`Shp` / `GeoJSON`
- 几何类型：`LineString`
- 当前强依赖字段：
  - `id`
  - `snodeid`
  - `enodeid`
  - `direction`
  - `formway`

### 2.2 Node

- 支持格式：`Shp` / `GeoJSON`
- 几何类型：`Point`
- 当前强依赖字段：
  - `id`
  - `kind`
  - `grade`
  - `closed_con`
- 当前语义聚合字段：
  - `mainnodeid`

### 2.3 输入处理前提

- 输入统一归一化到 `EPSG:3857`
- `mainnodeid` 为空、缺失、`0` 或空字符串时，回退到 `Node.id`
- `direction=0/1` 当前按双向处理
- 未正式启用字段不得因局部样本直接升级为强规则

## 3. formway 当前启用口径

### 3.1 Step1

- `formway bit7 = 右转专用道`
- 当前可用于 Step1 through incident degree 裁剪

### 3.2 Step2

- `formway bit8 = 左转专用道`
- 当前只用于 trunk 识别阶段
- 必须通过可配置模式启用：
  - `strict`
  - `audit_only`
  - `off`

## 4. Step1 输出契约

### 4.1 语义

- Step1 输出的是 `pair_candidates`
- Step1 不负责最终 Pair 有效性确认
- Step1 输出不能默认视为最终有效 Pair

### 4.2 当前输出文件

- `seed_nodes.geojson`
- `terminate_nodes.geojson`
- `pair_candidates.csv`
- `pair_candidate_nodes.geojson`
- `pair_links_candidates.geojson`
- `pair_support_roads.geojson`
- `pair_summary.json`
- `rule_audit.json`
- `search_audit.json`

### 4.3 兼容别名

- 当前仍保留：
  - `pair_nodes.geojson`
  - `pair_links.geojson`
  - `pair_table.csv`
- 这些文件仅用于兼容既有审查脚本
- 语义解释仍以 `pair_candidates` 为准

## 5. Step2 输出契约草案

### 5.1 语义

- Step2 = pair candidate validation + segment construction
- Step2 先判断 candidate 是否能够形成合法 Segment
- 只有通过验证的 candidate 才成为 `validated_pair`

### 5.2 当前原型输出

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

### 5.3 当前拒绝原因口径

- `invalid_candidate_boundary`
- `disconnected_after_prune`
- `no_valid_trunk`
- `only_clockwise_loop`
- `left_turn_only_polluted_trunk`
- `shared_trunk_conflict`
- `formway_unreliable_warning`

说明：

- `formway_unreliable_warning` 当前是 warning，不必然单独构成 reject
- reject / warning 最终是否封板，后续仍需业务确认

## 6. 审计与调试契约

- 所有关键拒绝原因必须在 `pair_validation_table.csv` 中显式可见
- 分支回溯裁剪痕迹必须落到 `branch_cut_roads.geojson`
- candidate / trunk / segment 的工作图过程必须可通过 `working_graph_debug.geojson` 回放
- 当前 `pair_summary.json` 与 `segment_summary.json` 都属于审查摘要，不是最终统计口径封板

## 7. 当前不承诺内容

- 多轮工作图剥离闭环
- T 型路口轮间复核完整实现
- 单向 Segment 输出契约
- trunk 冲突最终归属策略
- 生产级字段稳定性承诺
