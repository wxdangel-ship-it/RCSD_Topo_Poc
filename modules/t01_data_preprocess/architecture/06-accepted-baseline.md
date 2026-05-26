# 06 Accepted Baseline

## 1. 文档状态
- 状态：`accepted baseline / revised official alignment`
- 说明：
  - 本文档承载当前已确认的 T01 accepted baseline 业务口径。
  - 若实现与本文档冲突，应先视为实现待对齐，不得自行改写 accepted baseline。
  - 临时样例基线仅用于迭代中的最终 Segment 非回退检查，不覆盖本文档。

## 2. 目标
- 在非封闭式双向道路场景下，完成双向 Segment 构建。
- 支持多轮 residual graph 扩展。
- 在构段过程中滚动刷新 `grade_2 / kind_2` 当前语义。
- 在 Step6 完成 Segment 级聚合与合理性反查。

## 3. 官方输入与前置约束

### 3.1 官方输入
- `nodes.gpkg`
- `roads.gpkg`
- 兼容读取：
  - 同名 `GeoPackage(.gpkg)` 优先
  - 历史 `.gpkt` 仅兼容读取
  - `GeoJSON(.geojson/.json)` 与 `Shapefile(.shp)` 继续兼容

### 3.2 输入约束
- 当前双向 `Step1-Step5C` 主流程仅处理非封闭式道路路段构建。
- `Step5` 后单向补段允许处理 `road_kind = 1` 的封闭式 / 高速相关 road。
- node 侧输入约束：
  - `closed_con in {2,3}`
- road 侧输入约束：
  - 双向 `Step1-Step5C` 构段继续使用 `road_kind != 1`
  - `formway != 128`

### 3.3 working layers
- 模块开始阶段先建立 working layers。
- working nodes：
  - 复制输入 `nodes`
  - 新增：
    - `grade_2 = grade`
    - `kind_2 = kind`
- working roads：
  - 复制输入 `roads`
  - 新增：
    - `sgrade = null`
    - `segmentid = null`
- 后续所有业务判断统一使用：
  - `grade_2`
  - `kind_2`
- 原始 `grade / kind` 仅保留为原始输入信息，不再作为后续业务判断依据。
- working bootstrap 的执行顺序为：
  - 初始化 working fields
  - 环岛预处理
  - bootstrap node retyping
  - 再进入 Step1 / Step2

## 4. 开始阶段预处理

### 4.1 环岛预处理
- 提取 `roads` 中 `roadtype bit3` 的环岛 road。
- 仅按共享 node 的拓扑连通关系聚合，不按几何距离或 buffer 近邻聚合。
- 每组连通的环岛 roads 及其关联 nodes，视为一个语义路口。
- 选择组内 `id` 最小的 node 作为 `mainnode`。
- 对该 `mainnode`：
  - `grade_2 = 1`
  - `kind_2 = 64`
- 对组内其他 node：
  - `grade_2 = 0`
  - `kind_2 = 0`
- 该组所有 node 的 `mainnodeid` 统一刷为该 `mainnode`。

### 4.2 环岛后续语义
- 环岛与交叉路口均视为全通路口。
- Step1-Step5 中，原来使用 `kind_2 = 4` 作为全通路口输入的地方，均需纳入 `kind_2 = 64`。
- 环岛 `mainnode` 后续不参与 generic node 刷新规则。
- 环岛 `mainnode` 不被降级、不被改写为其他路口类型。

### 4.3 bootstrap node retyping
- 位于环岛预处理之后、Step1 之前。
- 仅允许修正 working node 的：
  - `grade_2`
  - `kind_2`
- 不改原始：
  - `grade`
  - `kind`
- 当前仅支持极窄的严格 T 型纠错，不做泛化节点重分类。
- 当前 bootstrap 纠错前提：
  - 当前节点为 `grade_2 = 1, kind_2 = 4`
  - 邻接总 family 数为 `3`
  - `segment_neighbor_family_count = 0`
  - `residual_neighbor_family_count = 3`
  - 仅存在 `1` 个 `has_in + has_out` 的 through family
  - 该 through family 的代表节点仍为 `grade_2 = 1, kind_2 = 4`
  - 其余两个 side family 都必须是单 road family，且满足：
    - 一个 side family 的代表节点为 `grade_2 = 1, kind_2 = 4`
    - 另一个 side family 的代表节点为 `kind_2 = 2048` 且 `grade_2 >= 2`
- 命中上述条件时，bootstrap 才允许将当前节点纠正为：
  - `grade_2 = 2`
  - `kind_2 = 2048`
- bootstrap 阶段当前不做：
  - `1/4 -> 2/4`
  - `1/4 -> 3/2048`

## 5. 全局双向构段硬约束
- 适用范围：
  - `Step2`
  - `Step4`
  - `Step5A`
  - `Step5B`
  - `Step5C`
- node 侧：
  - `closed_con in {2,3}`
- road 侧：
  - `road_kind != 1`
  - `formway != 128`
- 双线路段最小闭环上下行最大垂距门控：
  - `50m`
- 侧向旁路并入主路最大侧向距离门控：
  - `50m`

### 5.1 T 型路口竖向阻断规则
- 仅对应 `kind_2 = 2048`
- 不对应 `kind_2 = 4`
- 在 `Step2 / Step4 / Step5*` 中，只要该 T 型路口不是当前 segment 的起点 / 终点，都应禁止内部竖向追溯。
- 横方向允许继续追溯。

### 5.2 历史高等级边界
- 更低等级构段必须在更高等级历史路口中断。
- 解释：
  - 当更低等级轮次在 residual graph 上继续构段时，不能跨越已在更高等级轮次中作为段边界成立的语义路口。
- 当前轮 `terminate / hard-stop` 必须包含历史高等级边界 `mainnode`。
- 该边界同时作用于 pair 搜索阶段与 segment 收敛阶段。
- 命中历史边界时，记为 `terminal candidate`，并停止继续穿越。

### 5.3 分歧 / 合流局部续行规则
- `Road.kind` 字段已确认表达道路种别：单个 token 为 `XXXX`，前两位为道路等级，后两位为道路类型，多个 token 用 `|` 分隔。
- 该规则作用于 Step1 pair 搜索和 Step2 trunk simple-path 枚举的内部节点扩张，不改变 `seed / terminate / through_node_ids` 的定义。
- 在分歧 / 合流 / 低等级交叉路口存在多个可继续追溯出口时，先按进入 road 与退出 road 的 `kind` 前两位道路等级做局部过滤；若存在同等级退出 road，则优先保留同等级出口。
- 保留出口均为同等级时，再按进入方向与退出方向的夹角做二级消歧；夹角在最优值 `15°` 容差内的出口可同时保留。
- `Road.kind` 缺失或不可解析时，不通过几何形态反推道路等级；方向角只用于同等级候选的二级消歧。

## 6. 语义路口规则
- 若 `mainnodeid` 有值，则所有 `mainnodeid` 相同的 node 构成一个语义路口。
- 若 `mainnodeid` 为空，则该 node 自身就是独立语义路口。
- `mainnodeid = NULL` 不等于“不是路口”。
- 只要满足当前轮输入规则，就应正常进入 `seed / terminate`。

## 7. 阶段一：Step1

### 7.1 目标
- 基于当前轮输入规则，生成 `seed / terminate` 候选。
- 在当前工作图上做 pair 搜索。
- `through` 节点继续追溯。
- 仅输出 `pair_candidates`。
- Step1 不代表最终有效 pair。

### 7.2 首轮 Step1 输入规则
- `grade_2 in {1}`
- `kind_2 in {4,64}`
- `closed_con in {2,3}`
- `kind_2 = 128` 代表复杂分歧 / 合流路口组合；在双向首轮中，该复杂 mainnode 组不按 `mainnodeid` 聚合，而是拆回物理 `node.id` 建图，并以 raw `kind / grade` 作为组内物理 node 的有效规则字段，恢复独立分歧 / 合流语义；S2 seed / terminate 对该复杂组内物理 node 额外接受 raw `kind=8/16` 作为分歧 / 合流端点，不改变普通节点的 `kind_bits_any=[2,6]` 规则；Step2 不把复杂组合内部作为全局可枚举路口网处理，而优先按局部分歧 / 合流 port corridor 判定。
- `kind_2 = 128` 穿越审计独立于 `through_node_ids`：`through_node_ids` 仍只表达当前 degree-based through 规则命中的节点，不被扩展为复杂路口语义标签。

## 8. 阶段二：Step2

### 8.1 输入与输出
- 对 Step1 的 `pair_candidates` 做 `validated / rejected` 判定。
- 当前轮输入 / terminate 规则与首轮 Step1 一致：
  - `grade_2 in {1}`
  - `kind_2 in {4,64}`
  - `closed_con in {2,3}`
- 当前轮合法 `seed / terminate` 节点，不得被 `through_node` 吞掉。
- Step2 沿用 Step1 对 `kind_2 = 128` 复杂 mainnode 组拆回物理 node 级后的 candidate 支持路径，不扩展 `through_node_ids` 语义。
- Step2 对复杂 `kind_2 = 128` 组合优先采用 `kind2_128_local_corridor` 局部 port 判定：只基于 Step1 已确认的进入 / 退出支持路径及其局部门禁判断，不在复杂路口内部展开全局 simple-path 追溯。
- 当局部 corridor 本身未形成可终止的复杂组合，仍允许回退到既有精确判定；当局部 corridor 命中可终止复杂组合且门禁失败时，该 pair 以明确 reject reason 进入 rejected 输出，不再回退到复杂路口内部全局追溯。
- trunk search budget 保留为兜底保护；预算超限时，该 pair 以 `trunk_search_budget_exceeded` 进入 rejected 输出，不生成 segment body，并在 pair table 的 `support_info` 与 `segment_summary.json` 中保留预算配置、消耗、candidate/pruned road 数和 `kind_2 = 128` 节点数。
- `segment_summary.json` 与 pair table 必须统计经过 `kind_2 = 128` 的 candidate、validated、rejected、`dual_carriageway_separation_exceeded`、`kind2_128_local_corridor` 与 `trunk_search_budget_exceeded` 数量，用于定位复杂分歧 / 合流穿越对候选规模和性能的影响。
- 输出：
  - `validated`
  - `rejected`
  - `trunk`
  - `segment_body`
  - `step3_residual`

### 8.2 结果语义
- final segment 不再表达 all related roads，只表达当前 validated pair 的 pair-specific road body。

### 8.3 强规则
- `non-trunk component` 触达其他 terminate（非 A/B）时，不进入 `segment_body`。
- `non-trunk component` 吃到其他 validated pair 的 trunk 时，不进入 `segment_body`。

### 8.4 弱规则
- Step2 弱规则不在当前阶段硬删，统一进入 `step3_residual`。

### 8.5 trunk / 最小闭环语义
- `direction = 0/1` 的双向 road，业务上视为两条方向相反的可通行 road。
- 一条双向直连 road 的正反镜像通行，本身可构成合法最小闭环。
- trunk 支持 split-merge 混合通道：
  - 先分后合
  - 合后再分
  - 共享双向 road 的混合通道
- trunk 闭环语义以语义路口为单元，不再只依赖纯几何闭环。
- 若正反路径在 semantic-node-group 层面的有向图形成闭环，即使物理几何不开环，也可成立 trunk。

### 8.6 已确认修正
- 右转专用道误纳入已解决。
- `node = 791711` 的 T 型双向退出误追溯已解决。

## 9. 阶段三：Step3

### 9.1 目标
- 在 Step2 结果基础上，刷新 `nodes / roads` 当前语义。

### 9.2 Node 刷新
- 按 `mainnode` 执行，subnode 保持当前值。
- 优先级：
  1. 当前轮 validated pair 端点：保持当前值
  2. 所有 road 都在一个 segment 中：`grade_2 = -1, kind_2 = 1`
  3. 唯一 segment + 其余全是右转专用道：`grade_2 = 3, kind_2 = 1`
  4. 唯一 segment + 其余非segment road 同时存在 `in/out` 时，进入 family-based retyping：
     - 仅当当前节点为 `grade_2 = 1, kind_2 = 4`
     - 且 `total_neighbor_family_count = 3`
     - 且 `segment_neighbor_family_count = 1`
     - 且 `residual_neighbor_family_count = 2`
     - 若两个 residual family 都是 `simple_residual_family`，则纠正为 `grade_2 = 2, kind_2 = 2048`
     - 否则纠正为 `grade_2 = 2, kind_2 = 4`
  5. 否则保持当前值
- 环岛 `mainnode` 不参与 generic 刷新。

### 9.3 Road 刷新
- 已有非空 `segmentid / sgrade` 的 road 保持原值。
- Step2 新构成 road：`sgrade = 0-0双`

## 10. 阶段四：Step4

### 10.1 输入规则
- `grade_2 in {1,2}`
- `kind_2 in {4,64,2048}`
- `closed_con in {2,3}`

### 10.2 terminate / hard-stop
- 当前轮合法 terminate 集合与当前轮输入集合一致。
- 并入历史高等级边界端点。
- 当前轮合法 `seed / terminate` 节点，不得被 `through_node` 吞掉。

### 10.3 工作图
- 剔除已有非空 `segmentid` 的 road。
- 这些 road 在当前轮视为不存在。

### 10.4 共享约束
- 非封闭式道路过滤
- `50m` 上下行最大垂距门控
- `50m` 侧向并入距离门控
- 全局 T 型路口竖向阻断规则

### 10.5 输出
- `pair_candidates`
- `validated / rejected`
- `trunk`
- `segment_body`
- `residual`

### 10.6 Step4 后立即刷新
- Step4 结束后立即刷新 `nodes / roads` 当前语义，作为下一阶段输入。
- Node 刷新优先级：
  1. 当前轮 validated pair 端点：保持当前值
  2. 所有 road 都在一个 segment 中：`grade_2 = -1, kind_2 = 1`
  3. 唯一 segment + 其余全是右转专用道：`grade_2 = 3, kind_2 = 1`
  4. 唯一 segment + 其余非segment road 同时存在 `in/out` 时，执行与 Step3 相同的 family-based retyping
  5. 否则保持当前值
- 环岛 `mainnode` 不参与 generic 刷新。
- Step4 新构成 road：`sgrade = 0-1双`

## 11. 阶段五：Step5

### 11.1 总体原则
- Step5 不混成一轮平权构段。
- 拆为 `Step5A / Step5B / Step5C`。
- 三个子阶段按顺序执行。
- 每个子阶段完成后，都立即刷新当前 `nodes / roads` 属性。
- 下一子阶段使用上一子阶段 refreshed 的 `nodes / roads` 作为输入。
- 各子阶段工作图中，需剔除历史已有 `segmentid` 的 road，以及更早子阶段新构成的 `segment_body` road。

### 11.2 Step5A
- 输入规则：
  - `closed_con in {2,3}`
  - 且满足以下之一：
    - `kind_2 in {4,64,2048}` 且 `grade_2 in {1,2}`
    - `kind_2 in {4,64}` 且 `grade_2 = 3`
- terminate / hard-stop：
  - 当前轮合法 terminate 集合与当前轮输入集合一致
  - 并入 `S2 + Step4` 历史高等级边界端点
- 工作图：
  - 在 Step4 refreshed roads 基础上
  - 去掉历史已有 `segmentid` 的 road
- 语义：
  - 先处理当前更优先的一批双向路口主导的段
- 输出：
  - `pair_candidates`
  - `validated / rejected`
  - `trunk`
  - `segment_body`
  - `residual`
- 结束后立即刷新 `nodes / roads`
- Node 刷新规则与 Step4 一致
- 新构成 road：`sgrade = 0-2双`

### 11.3 Step5B
- 输入规则：
  - 基于 Step5A refreshed `nodes / roads`
  - `closed_con in {2,3}`
  - `kind_2 in {4,64,2048}`
  - `grade_2 in {1,2,3}`
- terminate / hard-stop：
  - 当前轮合法 terminate 集合与当前轮输入集合一致
  - 并入 `S2 + Step4` 历史高等级边界端点
  - Step5A 新端点只做 hard-stop，不回注入 Step5B 的 `seed / terminate`
- 工作图：
  - 在 Step5A 工作图上
  - 再剔除 Step5A 新构成的 `segment_body` road
- 语义：
  - 对 Step5A residual graph 上所有剩余双向路口做收尾构段
- 输出：
  - `pair_candidates`
  - `validated / rejected`
  - `trunk`
  - `segment_body`
  - `residual`
- 结束后立即刷新 `nodes / roads`
- Node 刷新规则与 Step4 一致
- 新构成 road：`sgrade = 0-2双`

### 11.4 Step5C
- 目标：
  - 在 residual graph 上，对前序切段后仍未被兜住的长 corridor 做最终 fallback
- 基础合法输入集合：
  - `closed_con in {2,3}`
  - `kind_2 in {4,64,2048}`
  - `grade_2 in {1,2,3}`
- seed 输入集合：
  - `rolling endpoint pool`
  - 组成：
    - 历史 validated endpoint `mainnode`
    - 当前 residual graph 上满足基础合法输入集合的语义路口
- terminate / hard-stop：
  - `protected hard-stop set`
    - 当前先只保护高置信语义路口：
      - 环岛 `mainnode`（`kind_2 = 64` 且 `closed_con in {2,3}`）
  - `actual barrier set`
    - 由 `rolling endpoint pool` 中未被 demote 且仍承担真实 barrier 语义的节点构成
- `demotable endpoint set`：
  - 从 `rolling endpoint pool` 中扣除 `protected hard-stop set`
  - 结合当前 residual graph 结构判定
  - 满足以下条件的 earlier endpoint，可降级为 through：
    - semantic-node-group 层 residual degree 退化
    - 不再承担真实 barrier 语义
- Step5C 语义：
  - `protected hard-stop`：命中即停
  - `demotable endpoint`：可继续 through
  - `actual barrier` 不再等于“所有历史 endpoint”
- Step5A / Step5B 仍保持严格 terminate 逻辑。
- Step5C 仍共享：
  - `50m` 上下行最大垂距门控
  - `50m` 侧向并入距离门控
  - 全局 T 型路口竖向阻断规则
- 输出：
  - `pair_candidates`
  - `validated / rejected`
  - `trunk`
  - `segment_body`
  - `residual`
- 结束后立即刷新 `nodes / roads`
- Node 刷新规则与 Step4 一致
- 新构成 road：`sgrade = 0-2双`

### 11.5 Step5 后单向补段
- 执行位置：
  - 在 `Step5C` refreshed `nodes / roads` 之后
  - 在 `Step6` 聚合之前
- 作用边界：
  - 仅补齐仍未被双向 Segment 构成的单向 road
  - 不回写 `Step2 / Step4 / Step5A / Step5B / Step5C` 的双向构段规则
- road 过滤：
  - 已有非空 `segmentid` 的 road 不再进入单向阶段
  - `formway = 128` 与右转专用道不参与
  - `road_kind = 1` 允许进入单向阶段，仅用于封闭式 / 高速相关单向补段
- 阶段定义：
  - `0-0单`：`closed_con in {1,3}`、`kind_2 in {8,16}`、`grade_2 = 1`
  - `0-1单`：`closed_con in {2,3}`、`kind_2 in {4,8,16,64,128,2048}`、`grade_2 in {1,2}`
  - `0-2单`：`closed_con in {2,3}`、`kind_2 in {4,8,16,64,128,2048}`、`grade_2 in {1,2,3}`
- `kind_2 = 128` 代表复杂分歧 / 合流路口；当前仅纳入 `0-1单 / 0-2单`，不纳入 `0-0单`。
- 新构成 road：`sgrade = 0-0单 / 0-1单 / 0-2单`
- dead-end leaf 补段：
  - 在常规单向 terminate-to-terminate 补段之后、`Step6` 之前执行
  - 只处理仍未构段且满足排除规则的 residual road bundle
  - 支持两种 bundle 形态：
    - 单条 `direction in {0,1}` 的双向 road，且继续遵守双向 `road_kind != 1`
    - 两条方向互补的 `direction in {2,3}` 单向 road，允许沿用单向阶段的 `road_kind = 1` 放开口径
  - bundle 两端必须恰有一端满足合法语义端点，另一端为 leaf node
  - leaf node 端不得存在该 bundle 之外的其他有效 residual 延展
  - 单条未成对单向 road 暂不作为 dead-end leaf Segment 构建
  - 新构成 road：`sgrade = 0-2双`
  - 新构成 road 写入审计 / 发布保护字段：
    - `segment_build_source = dead_end_leaf`
    - `leaf_node_id = <leaf semantic node id>`
    - `dead_end_bundle_type in {bidirectional, reciprocal_oneway}`
- 未构段 road 审计：
  - `unsegmented_roads.csv` 输出 `formway_has_bit7_or_bit8` 与 `audit_reason`
  - `unsegmented_roads_summary.json` 统计最终仍未构段且 `formway` 不含 bit7 / bit8 的 road 数量
  - 同一 summary 输出上述非 bit7 / bit8 未构段 road 的 `audit_reason` 分布
  - 该审计口径只解释最终 residual road，不回写构段规则

## 12. 阶段六：Step6

### 12.1 输入
- 最新的 refreshed `nodes.gpkg`
- 最新的 refreshed `roads.gpkg`

### 12.2 输出
- `segment.gpkg`
- `inner_nodes.gpkg`
- `segment_error.gpkg`
- `segment_error_s_grade_conflict.gpkg`
- `segment_error_grade_kind_conflict.gpkg`

### 12.3 segment.gpkg
- `id`：与 `roads.segmentid` 相同
- `geometry`：该 Segment 下所有 road 构成的 `MultiLineString`
- `sgrade`：与 `roads.sgrade` 对应
- `pair_nodes`：
  - Segment 两端端点对应的 `mainnodeid`
  - 以逗号隔开
  - 顺序按 `segmentid` 中 `A_B` 顺序
  - 若 `mainnodeid` 为空，则用该 node 自身 `id`
- `junc_nodes`：
  - Segment 中除两端外，仍存在去往当前 Segment 外其他方向的语义路口 `mainnodeid`
  - 以逗号隔开
  - 去重
- `roads`：
  - Segment 下所有 road 的 `id`
  - 以逗号隔开

### 12.4 inner_nodes.gpkg
- 若某语义路口的所有分支 road 都在同一个 Segment 内，则该路口不进入 `junc_nodes`。
- 该路口内所有 node 完整复制到 `inner_nodes.gpkg`。

### 12.5 Step6 规则
- 规则1：
  - 若某 Segment 两端路口 `grade_2` 都为 `1`，且 `sgrade != 0-0双`，则将其 `sgrade` 调整为 `0-0双`
  - 但单向 Segment 与 dead-end leaf Segment 不适用该提升规则
- 规则2：
  - 对所有 `sgrade = 0-0双` 的 Segment，其 `junc_nodes` 下的所有路口类型都不能为：
    - `grade_2 = 1`
    - 且 `kind_2 = 4`
  - 若存在，则输出到 `segment_error.gpkg`
  - 并按错误类型拆分输出到：
    - `segment_error_s_grade_conflict.gpkg`
    - `segment_error_grade_kind_conflict.gpkg`

## 13. 当前已固化内容
- Step1 只输出 `pair_candidates`
- Step2 输出 `validated / rejected / trunk / segment_body / step3_residual`
- final segment 只表达 pair-specific road body
- Step2 强规则已固化：
  - `non-trunk component` 触达其他 terminate（非 A/B）时，不进入 `segment_body`
  - `non-trunk component` 吃到其他 validated pair 的 trunk 时，不进入 `segment_body`
- 全局 T 型路口竖向阻断规则已上提为统一约束
- 右转专用道误纳入已解决
- `791711` 的 T 型双向退出误追溯已解决
- residual graph 多轮构段语义已固化
- historical higher-level boundary 语义已固化
- working nodes / roads 初始化已前置
- 环岛预处理已纳入开始阶段
- bootstrap node retyping 已纳入开始阶段
- family-based refresh retyping 已替代旧的 generic `t_like => 2048` 叙述
- Step6 已纳入当前需求口径

## 14. 当前仍需继续验证 / 修正
- 少量 `Step1-Step5C` 的未构出 / 误构出场景
- Step5C final fallback 的 adaptive barrier 语义仍需继续验证
- 环岛以外更多特殊路口的新规则
- Step6 之后的最终拓扑治理闭环
- 单向 Segment
- Step3 完整语义归并
- 更完整的测试 / 回归 / 验收体系

## 15. 对齐原则
- 若 T01 仓库文档与本规格冲突，以最新确认的业务口径为准。
- 若实现与本文档冲突，需先说明文档歧义，再由用户拍板。
- 未经允许，不修改已固化的 T01 accepted baseline。
- 后续 T02 / T03 等模块消费 T01 结果时，默认以：
  - refreshed `nodes.gpkg`
  - refreshed `roads.gpkg`
  - `segment.gpkg`
  作为标准输入理解基础。
