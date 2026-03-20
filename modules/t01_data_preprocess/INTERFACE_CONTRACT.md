# T01 - INTERFACE_CONTRACT

## 1. 文档状态
- 状态：`accepted baseline contract / current active baseline`
- 用途：固化当前 working layer、环岛预处理、Step1-Step5 输入约束、distance gate、活动基线 compare 契约

## 2. Raw input layer
- Road 支持：`Shp` / `GeoJSON`
- Node 支持：`Shp` / `GeoJSON`
- raw input 必须保留：
  - Node：`kind`、`grade`、`closed_con`
  - Road：原始 road 字段集合，包含 `road_kind`、`roadtype` 等
- raw input 不允许被后续业务覆盖写入

## 3. Working Nodes / Roads

### 3.1 Working Nodes
- 模块开始即生成 working nodes
- 必备字段：
  - `id`
  - `mainnodeid`
  - `closed_con`
  - `grade`
  - `kind`
  - `grade_2`
  - `kind_2`
- 初始化规则：
  - `grade_2 = grade`
  - `kind_2 = kind`

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
  - 全组 `mainnodeid` 刷为该 `mainnode`
- 环岛 `mainnode` 保护：
  - 后续 generic refresh 必须跳过
  - 保持 `grade_2 = 1`、`kind_2 = 64`

## 5. 正式业务字段
- Step1 / Step2 / Step4 / Step5A / Step5B / Step5C 一律操作 working layers
- 后续业务判断统一基于：
  - `grade_2`
  - `kind_2`
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

### 8.3 Step3
- 刷新 working Nodes / Roads
- 将首轮构段结果写入 `grade_2 / kind_2 / segmentid / s_grade`

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

### 8.5 Step5A
- 输入筛选：
  - `closed_con in {2,3}`
  - 且：
    - `kind_2 in {4,64,2048}` 且 `grade_2 in {1,2}`
    - 或 `kind_2 in {4,64}` 且 `grade_2 = 3`
- Step5A 消费 `Step4` 的全量 endpoint pool

### 8.6 Step5B
- 输入筛选：
  - `closed_con in {2,3}`
  - `kind_2 in {4,64,2048}`
  - `grade_2 in {1,2,3}`
- Step5B 消费 `Step5A` 的全量 endpoint pool
- 当前轮新增合法端点并入同一 endpoint pool
- 端点仍保持 `hard-stop`

### 8.7 Step5C
- 输入筛选：
  - `closed_con in {2,3}`
  - `kind_2 in {1,4,64,2048}`
  - `grade_2 in {1,2,3}`
- Step5C 消费 `Step5B` 的全量 endpoint pool
- 当前轮新增合法端点并入同一 endpoint pool
- 端点仍保持 `hard-stop`

### 8.8 staged runner 统一行为
- `force_seed / force_terminate / hard-stop` 统一基于滚动 endpoint pool
- 传递顺序：
  - `Step4 <- Step2 endpoint pool`
  - `Step5A <- Step4 endpoint pool`
  - `Step5B <- Step5A endpoint pool`
  - `Step5C <- Step5B endpoint pool`
- endpoint pool 传递的是全量 `seed / terminate` 端点池，不是只传 validated pair 端点
- 若某端点在当前 working graph 上已无剩余可用 road，会自然退出下一轮

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
- official runner 最终输出：
  - `nodes.geojson`
  - `roads.geojson`
  - `validated_pairs_skill_v1.csv`
  - `segment_body_membership_skill_v1.csv`
  - `trunk_membership_skill_v1.csv`
  - `skill_v1_manifest.json`
  - `skill_v1_summary.json`

## 11. 活动基线 compare 契约
- 当前活动基线为三样例套件：
  - `modules/t01_data_preprocess/baselines/t01_skill_active_three_sample_suite/XXXS/`
  - `modules/t01_data_preprocess/baselines/t01_skill_active_three_sample_suite/XXXS2/`
  - `modules/t01_data_preprocess/baselines/t01_skill_active_three_sample_suite/XXXS3/`
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
