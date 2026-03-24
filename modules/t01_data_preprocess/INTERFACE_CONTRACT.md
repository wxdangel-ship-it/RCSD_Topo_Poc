# T01 - INTERFACE_CONTRACT

## 1. 文档定位
- 状态：`accepted baseline contract / revised alignment`
- 用途：
  - 固化 T01 working layers、阶段输入输出、正式字段约束与 Step6 聚合契约
  - 作为模块级 source of truth 摘要
- 主业务规格以：
  - `/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/architecture/06-accepted-baseline.md`
  为准

## 2. 官方输入契约
- 官方输入：
  - `nodes.gpkg`
  - `roads.gpkg`
- 兼容读取：
  - 同名 `GeoPackage(.gpkg)` 优先
  - 历史 `.gpkt` 仅兼容读取
  - `GeoJSON(.geojson/.json)` 与 `Shapefile(.shp)` 继续兼容
- node 输入约束：
  - `closed_con in {2,3}`
- road 输入约束：
  - `road_kind != 1`
  - `formway != 128`

## 3. Working Layers

### 3.1 Working Nodes
- 必备字段：
  - `id`
  - `mainnodeid`
  - `closed_con`
  - `grade`
  - `kind`
  - `grade_2`
  - `kind_2`
- 初始化：
  - `grade_2 = grade`
  - `kind_2 = kind`
- 后续业务判断统一使用：
  - `grade_2`
  - `kind_2`
- raw `grade / kind` 不得再进入后续业务强规则。

### 3.2 Working Roads
- 必备字段：
  - `id`
  - `snodeid`
  - `enodeid`
  - `direction`
  - `formway`
  - `road_kind`
  - `segmentid`
  - `sgrade`
- 初始化：
  - `segmentid = null`
  - `sgrade = null`

## 4. 预处理契约

### 4.1 环岛预处理
- roundabout preprocessing 位于 bootstrap 之后、Step1 之前。
- 环岛 `mainnode`：
  - `grade_2 = 1`
  - `kind_2 = 64`
- 环岛 member node：
  - `grade_2 = 0`
  - `kind_2 = 0`
- 该组所有 node 的 `mainnodeid` 统一写为环岛 `mainnode`。
- 环岛 `mainnode` 后续不参与 generic node 刷新。

### 4.2 右转专用道契约
- `formway = 128` 的 road 不得进入 Step1-Step5 的 Segment 构建图。
- 去除右转专用道后若节点不再构成真实路口，则该节点不得作为：
  - `seed / terminate`
  - `through`
  - `boundary / endpoint pool`
  - Step6 的有效外向语义路口

## 5. Step1-Step5C 阶段契约

### 5.1 全局共享约束
- node：
  - `closed_con in {2,3}`
- road：
  - `road_kind != 1`
  - `formway != 128`
- gates：
  - `MAX_DUAL_CARRIAGEWAY_SEPARATION_M = 50.0`
  - `MAX_SIDE_ACCESS_DISTANCE_M = 50.0`

### 5.2 T 型路口竖向阻断
- 仅对应 `kind_2 = 2048`
- 不对应 `kind_2 = 4`
- 在 `Step2 / Step4 / Step5A / Step5B / Step5C` 中：
  - 若该 T 型路口不是当前 segment 的起点 / 终点，则禁止内部竖向追溯
  - 横方向允许继续追溯

### 5.3 历史高等级边界
- 更低等级构段不得跨越更高等级轮次中已成立的段边界语义路口。
- 当前轮 `terminate / hard-stop` 必须并入历史高等级边界 `mainnode`。

### 5.4 Step1
- 输入：
  - 首轮 `grade_2 in {1}`
  - `kind_2 in {4,64}`
  - `closed_con in {2,3}`
- 输出：
  - `pair_candidates`

### 5.5 Step2
- 输入 / terminate 规则与首轮 Step1 一致。
- 合法 `seed / terminate` 节点不得被 `through_node` 吞掉。
- 输出：
  - `validated`
  - `rejected`
  - `trunk`
  - `segment_body`
  - `step3_residual`
- final segment 仅表达 pair-specific road body。
- 强规则：
  - `non-trunk component` 触达其他 terminate（非 A/B）时，不进入 `segment_body`
  - `non-trunk component` 吃到其他 validated pair 的 trunk 时，不进入 `segment_body`

### 5.6 Step3
- Node 刷新优先级：
  1. 当前轮 validated pair 端点：保持当前值
  2. 所有 road 都在一个 segment 中：`grade_2 = -1, kind_2 = 1`
  3. 唯一 segment + 其余全是右转专用道：`grade_2 = 3, kind_2 = 1`
  4. 唯一 segment + 其余非segment road 构成多进多出：`grade_2 = 2, kind_2 = 2048`
  5. 否则保持当前值
- Step2 新构成 road：
  - `sgrade = 0-0双`

### 5.7 Step4
- 输入：
  - `grade_2 in {1,2}`
  - `kind_2 in {4,64,2048}`
  - `closed_con in {2,3}`
- 当前轮合法 terminate 集合与输入集合一致。
- 并入历史高等级边界端点。
- 工作图剔除已有非空 `segmentid` 的 road。
- 阶段结束后立即刷新 `nodes / roads`。
- Step4 新构成 road：
  - `sgrade = 0-1双`

### 5.8 Step5A / Step5B / Step5C
- 三个子阶段按顺序执行。
- 每个子阶段结束后，都立即刷新 `nodes / roads`。
- 下一子阶段使用上一子阶段 refreshed 的 `nodes / roads`。
- 各子阶段工作图中，剔除历史已有 `segmentid` 的 road，以及更早子阶段新构成的 `segment_body` road。

#### Step5A
- 输入：
  - `closed_con in {2,3}`
  - 且满足以下之一：
    - `kind_2 in {4,64,2048}` 且 `grade_2 in {1,2}`
    - `kind_2 in {4,64}` 且 `grade_2 = 3`
- 并入 `S2 + Step4` 历史高等级边界端点。
- 新构成 road：
  - `sgrade = 0-2双`

#### Step5B
- 输入：
  - 基于 Step5A refreshed `nodes / roads`
  - `closed_con in {2,3}`
  - `kind_2 in {4,64,2048}`
  - `grade_2 in {1,2,3}`
- 并入 `S2 + Step4` 历史高等级边界端点。
- Step5A 新端点只做 hard-stop，不回注入 Step5B 的 `seed / terminate`。
- 新构成 road：
  - `sgrade = 0-2双`

#### Step5C
- 基础合法输入集合：
  - `closed_con in {2,3}`
  - `kind_2 in {4,64,2048}`
  - `grade_2 in {1,2,3}`
- `rolling endpoint pool`：
  - 历史 validated endpoint `mainnode`
  - 当前 residual graph 上满足基础合法输入集合的语义路口
- `protected hard-stop set`：
  - 当前只保护环岛 `mainnode`
- `demotable endpoint set`：
  - 从 `rolling endpoint pool` 中扣除 `protected hard-stop set`
  - 再按 residual degree 与 barrier 语义退化判定
- `actual barrier` 不再等于“所有历史 endpoint”
- 新构成 road：
  - `sgrade = 0-2双`

## 6. Step6 契约

### 6.1 输入
- 最新 refreshed `nodes.gpkg`
- 最新 refreshed `roads.gpkg`

### 6.2 输出
- `segment.gpkg`
- `inner_nodes.gpkg`
- `segment_error.gpkg`

### 6.3 聚合字段
- `segment.gpkg`
  - `id = segmentid`
  - `geometry = MultiLineString`
  - `sgrade`
  - `pair_nodes`
  - `junc_nodes`
  - `roads`
- `pair_nodes`
  - 按 `segmentid` 中 `A_B` 顺序解析
  - 若端点 `mainnodeid` 为空，则回退该 node 自身 `id`
- `inner_nodes.gpkg`
  - 复制被单一 Segment 完整内含的语义路口所有 node

### 6.4 Step6 规则
- 规则1：
  - 若某 Segment 两端路口 `grade_2` 都为 `1`，且 `sgrade != 0-0双`，则调整为 `0-0双`
- 规则2：
  - 对所有 `sgrade = 0-0双` 的 Segment，若其中间 `junc_nodes` 存在：
    - `grade_2 = 1`
    - 且 `kind_2 = 4`
    则输出到 `segment_error.geojson`
- Step6 对 `junc_nodes / inner_nodes / segment_error` 的判断，应与全局 `formway != 128` 约束保持一致。

## 7. 文档与实现边界
- 本契约只描述当前 accepted baseline 下的对外契约与阶段约束。
- 临时样例基线与结构整改进度不写入本契约正文。
- 若实现与本契约冲突，应先修实现或提交歧义说明，不得自行覆盖 accepted baseline。
