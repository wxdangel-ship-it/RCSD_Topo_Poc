# T01 - INTERFACE_CONTRACT

## 1. 文档状态
- 状态：`accepted baseline contract / current active baseline`
- 用途：固化当前 working layer、环岛预处理、Step1-Step5 输入约束、distance gate、活动基线 compare 契约

## 2. Raw input layer
- Road 支持：`Shp` / `GeoJSON`
- Node 支持：`Shp` / `GeoJSON`
- raw input 必须保留：
  - Node：`kind`、`grade`、`closed_con`、`mainnodeid`（若输入存在）
  - Road：原始 road 字段集合，包含 `road_kind`、`roadtype` 等
- raw input 不允许被后续业务覆盖写入

## 3. Working Nodes / Roads

### 3.1 Working Nodes
- 模块开始即生成 working nodes
- 必备字段：
  - `id`
  - `mainnodeid`
  - `working_mainnodeid`
  - `closed_con`
  - `grade`
  - `kind`
  - `grade_2`
  - `kind_2`
- 初始化规则：
  - `grade_2 = grade`
  - `kind_2 = kind`
  - `working_mainnodeid = mainnodeid`
- 保真约束：
  - `mainnodeid` 保持 raw input 原值，不参与后续运行期改写
  - 运行期 `mainnode` 语义一律写入 `working_mainnodeid`

### 3.2 Working Roads
- 模块开始即生成 working roads
- 必备字段：
  - `id`
  - `snodeid`
  - `enodeid`
  - `direction`
  - `formway`
  - `roadtype`
  - `road_kind`
  - `s_grade`
  - `segmentid`
- 初始化规则：
  - `s_grade = null`
  - `segmentid = null`

## 4. 环岛语义
- 环岛 road 识别：
  - 字段：`roadtype`
  - 位判定：`bit3 = 8`
- 聚合方式：
  - 仅按共享 node 的拓扑连通关系聚组
- 每组输出规则：
  - 最小 node id 为 `mainnode`
  - `mainnode`：`grade_2 = 1`、`kind_2 = 64`
  - `member node`：`grade_2 = 0`、`kind_2 = 0`
  - 全组 `working_mainnodeid` 刷为该 `mainnode`
- 环岛 `mainnode` 保护：
  - 后续 generic refresh 必须跳过
  - 保持 `grade_2 = 1`、`kind_2 = 64`

## 5. 正式业务字段
- Step1 / Step2 / Step4 / Step5A / Step5B / Step5C 一律操作 working layers
- 后续业务判断统一基于：
  - `grade_2`
  - `kind_2`
  - `working_mainnodeid`
  - `closed_con`
  - `segmentid`
  - `s_grade`
- raw `grade / kind` 只允许用于：
  - bootstrap 初始化
  - 审计 / 展示 / 回报
  - 测试夹具

## 6. 当前正式输入约束

### 6.1 node
- 当前双向道路构段场景统一要求：
  - `closed_con in {2,3}`
- 适用范围：
  - seed / terminate
  - boundary / hard-stop
  - 当前轮合法输入节点
  - residual graph 下一轮输入节点

### 6.2 road
- 当前双向道路构段场景统一要求：
  - `road_kind != 1`
- 适用范围：
  - working graph
  - pair candidate 搜索图
  - trunk validation
  - segment 收敛
  - residual graph 后续轮次工作图

## 7. 全通路口输入扩容
- `kind_2 = 4`：交叉路口
- `kind_2 = 64`：环岛 `mainnode`
- `kind_2 = 2048`：T 型路口
- 凡属“全通路口”语义位置，必须接受：
  - `kind_2 in {4,64}`
- 凡属“交叉 + 环岛 + T”语义位置，必须接受：
  - `kind_2 in {4,64,2048}`

## 8. Step1-Step5 阶段契约

### 8.1 Step1
- 输出：`pair_candidates`
- 不代表最终有效 pair
- 当前 seed / terminate 契约：
  - `S1 seed`：
    - `closed_con in {2,3}`
    - `kind_2 in {4,64}`
  - `S1 terminate`：
    - `closed_con in {2,3}`
    - `kind_2 in {4,64}`
  - `S2 seed`：
    - `closed_con in {2,3}`
    - `kind_2 in {4,64}`
    - `grade_2 = 1`
  - `S2 terminate`：
    - `closed_con in {2,3}`
    - `kind_2 in {4,64}`
    - `grade_2 = 1`
- 当前继续追踪约束：
  - T 型路口不是 Step1 terminate
  - 局部分歧 / 合流节点不会仅因节点类型本身被强制终止；是否继续追踪仍以 `through_node_rule` 与 `hard-stop` 判定为准

### 8.2 Step2
- 输出：
  - `validated_pairs`
  - `rejected_pair_candidates`
  - `trunk_roads`
  - `segment_body_roads`
  - `step3_residual_roads`
  - `pair_validation_table`
  - `segment_summary.json`
- `segment_body_roads` 只表达当前 validated pair 的 pair-specific road body
- 同时输出首轮全量 `endpoint_pool.csv`
- Step2 不新增 seed / terminate 规则，只消费 Step1 `pair_candidates`
- Step2 当前待收敛候选策略：
  - `XXXS` 审计表明：存在“内部路口挂接侧向结构不应在 Step2 直接并入当前主 Segment”的现象
  - 候选规则的语义核心是：
    - 在主 Segment 内部 support node 上，先识别 trunk / support path 的本地主通行 `I` 向
    - 只有不属于 `I` 向延续的 incident road，才视为侧向 branch 候选
    - 单侧旁路的分支必须与当前 Segment 该侧通行方向一致；反方向 branch 不能保留
    - side subgraph 可以包含多条单向平行侧路及其短小连接路，但整体必须仍然表达“单侧旁路系统”，不能借内部路口的 `I` 向再次串成内部挂接网
  - 当前不将以下条件直接定义为 accepted baseline 硬规则：
    - `one_way_parallel`
    - `attachment_node_ids` 全部命中内部 T 型 support node
    - `attachment_node_ids` 个数或“简单路径”图论形态
  - 下一轮应继续基于 `XXXS / XXXS3 / XXXS4` 的目标拓扑收敛更窄触发条件；在规则正式确认前，不将其作为模块 accepted baseline 契约

### 8.3 Step3
- 刷新 working Nodes / Roads
- 将首轮构段结果写入 `grade_2 / kind_2 / segmentid / s_grade`
- Step3 不做 pair 搜索，因此没有新的 seed / terminate 判定

### 8.4 Step4
- 输入必须已包含 working fields
- 缺失 `grade_2 / kind_2 / s_grade / segmentid` 时 fail fast
- 输入筛选：
  - `grade_2 in {1,2}`
  - `kind_2 in {4,64,2048}`
  - `closed_con in {2,3}`
- 工作图剔除：
  - 已有非空 `segmentid` 的 road
  - `road_kind = 1` 的 road
- Step4 消费 `Step2` 的全量 endpoint pool
- Step4 seed / terminate 输入条件：
  - seed 来源：
    - `Step2` 滚动下来的全量 endpoint pool
    - 当前 Step4 新增满足输入筛选的节点
  - terminate 来源：
    - 与 seed 同一 endpoint pool
    - 历史边界仍同时进入 `hard-stop`
  - 生成的 Step4 working graph 会把当前轮 eligible endpoint 统一规范化为可搜索节点；审计时以输入筛选条件和 endpoint pool 为准，不以中间 working graph 上的归一化 `kind_2 / grade_2` 误判业务语义

### 8.5 Step5A
- 输入筛选：
  - `closed_con in {2,3}`
  - 且：
    - `kind_2 in {4,64,2048}` 且 `grade_2 in {1,2}`
    - 或 `kind_2 in {4,64}` 且 `grade_2 = 3`
- Step5A 消费 `Step4` 的全量 endpoint pool
- Step5A seed / terminate 输入条件：
  - seed 来源：
    - `Step4` 滚动下来的全量 endpoint pool
    - 当前 Step5A 新增满足输入筛选的节点
  - terminate 来源：
    - 与 seed 同一 endpoint pool
    - 历史边界仍同时进入 `hard-stop`

### 8.6 Step5B
- 输入筛选：
  - `closed_con in {2,3}`
  - `kind_2 in {4,64,2048}`
  - `grade_2 in {1,2,3}`
- Step5B 消费 `Step5A` 的全量 endpoint pool
- 当前轮新增合法端点并入同一 endpoint pool
- 端点仍保持 `hard-stop`
- Step5B seed / terminate 输入条件：
  - seed 来源：
    - `Step5A` 滚动下来的全量 endpoint pool
    - 当前 Step5B 新增满足输入筛选的节点
  - terminate 来源：
    - 与 seed 同一 endpoint pool
    - 同一批滚动端点继续保持 `hard-stop`

### 8.7 Step5C
- Step5C 是 final fallback 轮，不再沿用 `Step5A / Step5B` 的机械 terminate 继承。
- Step5C 输入筛选拆成 4 个集合：
  - `rolling endpoint pool`
  - `protected hard-stop set`
  - `demotable endpoint set`
  - `actual terminate barriers`
- `rolling endpoint pool`：
  - 来源：
    - `Step5B` 滚动下来的历史 endpoint mainnode
    - 并上当前 residual graph 中满足：
      - `closed_con in {2,3}`
      - `kind_2 in {4,64,2048}`
      - `grade_2 in {1,2,3}`
      的语义路口
  - 约束：
    - `kind_2 = 1` 不能仅因字段条件进入 pool
    - 若 `kind_2 = 1` 节点留在 pool，只能因历史 endpoint 身份进入
- `protected hard-stop set`：
  - 当前只保留高置信对象：
    - 环岛 mainnode（`kind_2 = 64` 且 `closed_con in {2,3}`）
- `demotable endpoint set`：
  - 来源：`rolling endpoint pool - protected hard-stop set`
  - 在当前 `Step5C residual graph` 上按 semantic-node-group 判定
  - 当前最小正式判据：
    - `semantic incident degree = 2`
    - 且 `distinct neighbor semantic groups = 2`
- `actual terminate barriers`：
  - 由 `protected hard-stop set`
  - 加上当前 residual graph 上未被 demote、仍保持真实 barrier 语义的 endpoint
  共同构成
- Step5C seed / terminate / hard-stop 关系：
  - seed 候选来源：`rolling endpoint pool`
  - terminate 来源：`actual terminate barriers`
  - hard-stop 来源：`protected hard-stop set`
  - 已 demote endpoint：
    - 仍可保留 rolling endpoint 历史身份
    - 但不再强制 terminate / hard-stop
    - 允许在 Step5C 作为 through 继续穿过

### 8.8 staged runner 统一行为
- 传递顺序：
  - `Step4 <- Step2 endpoint pool`
  - `Step5A <- Step4 endpoint pool`
  - `Step5B <- Step5A endpoint pool`
  - `Step5C <- Step5B endpoint pool`
- endpoint pool 传递的是全量 `seed / terminate` 端点池，不是只传 validated pair 端点
- 若某端点在当前 working graph 上已无剩余可用 road，会自然退出下一轮
- `Step4 / Step5A / Step5B`：
  - 继续沿用 strict staged 模式
  - `force_seed / force_terminate / hard-stop` 仍按滚动 endpoint pool 刚性继承
- `Step5C`：
  - 改为 adaptive barrier fallback
  - `force_seed` 使用 `rolling endpoint pool`
  - `force_terminate` 使用 `actual terminate barriers`
  - `hard-stop` 使用 `protected hard-stop set`
  - 搜索与后续 segment 收敛阶段都必须使用同一套 `actual barrier` 语义

### 8.9 Step5C 审计输出契约
- `STEP5C` debug 目录必须输出：
  - `step5c_rolling_endpoint_pool.csv`
  - `step5c_rolling_endpoint_pool.geojson`
  - `step5c_protected_hard_stops.csv`
  - `step5c_protected_hard_stops.geojson`
  - `step5c_demotable_endpoints.csv`
  - `step5c_demotable_endpoints.geojson`
  - `step5c_actual_barriers.csv`
  - `step5c_actual_barriers.geojson`
  - `step5c_endpoint_demote_audit.json`
  - `target_pair_audit_997356__39546395.json`
- `step5c_endpoint_demote_audit.json` 至少包含：
  - `node_id`
  - `is_historical_endpoint`
  - `is_current_input_candidate`
  - `is_protected_hard_stop`
  - `semantic_incident_degree`
  - `distinct_neighbor_group_count`
  - `demoted`
  - `reason`
- `target_pair_audit_997356__39546395.json` 至少包含：
  - `entered_step5c_candidate`
  - `entered_step5c_validated`
  - `blocked_by_actual_barrier`
  - `blocking_barrier_node_ids`
  - `remaining_blocker_type`
  - `remaining_blocker_detail`
  - `terminate_rigidity_cleared`

## 9. 距离 gate 契约
- 以下 trunk / segment 提取约束在 `Step2 / Step4 / Step5A / Step5B / Step5C` 共享。

### 9.1 trunk / 最小闭环 gate
- 常量：`MAX_DUAL_CARRIAGEWAY_SEPARATION_M = 50.0`
- 用途：限制上下行最大垂距
- 结果：
  - 超限时拒绝理由：`dual_carriageway_separation_exceeded`
  - 审计字段：`dual_carriageway_max_separation_m`

### 9.2 side component / 旁路 gate
- 常量：`MAX_SIDE_ACCESS_DISTANCE_M = 50.0`
- 用途：限制旁路并入主路段时的最大侧向距离
- 结果：
  - 超限时 residual 原因：`side_access_distance_exceeded`
  - 审计字段：`side_access_distance_m`

## 10. 最终输出契约
- official runner 若未显式传入 `--out-root`，默认输出根目录为：
  - `outputs/_work/t01_skill_eval/<run_id>/`
- official runner 最终输出：
  - `nodes.geojson`
  - `roads.geojson`
  - `validated_pairs_skill_v1.csv`
  - `segment_body_membership_skill_v1.csv`
  - `trunk_membership_skill_v1.csv`
  - `skill_v1_manifest.json`
  - `skill_v1_summary.json`

## 11. 活动基线 compare 契约
- 当前活动基线为五样例套件：
  - `modules/t01_data_preprocess/baselines/t01_skill_active_five_sample_suite/XXXS/`
  - `modules/t01_data_preprocess/baselines/t01_skill_active_five_sample_suite/XXXS2/`
  - `modules/t01_data_preprocess/baselines/t01_skill_active_five_sample_suite/XXXS3/`
  - `modules/t01_data_preprocess/baselines/t01_skill_active_five_sample_suite/XXXS4/`
  - `modules/t01_data_preprocess/baselines/t01_skill_active_five_sample_suite/XXXS5/`
- 逐样例 compare 仍使用官方入口：
  - `python -m rcsd_topo_poc t01-compare-freeze`
- compare 时应将对应样例 current run 与同名 freeze 子目录逐一对比。
- 后续性能优化、结构重构或规则调整，只要任一样例不一致，都必须先由用户复核后再决策。

## 12. 历史归档基线
- 旧单样例 baseline：
  - `modules/t01_data_preprocess/baselines/t01_skill_v1_0_xxxs/`
- 旧语义修正 candidate：
  - `modules/t01_data_preprocess/baselines/t01_skill_v1_0_xxxs_semantic_fix_candidate/`
- 上述目录保留为历史追溯材料，不再作为当前活动基线。
