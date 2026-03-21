# T01 数据预处理 Skill 规格

## 1. 当前业务目标
- T01 模块当前完成的总体业务目标是：对普通道路网络中，从高等级到低等级，逐级提取双向联通的路段，为后续关键路口锚定和路段构建打基础。
- 当前主线只覆盖普通道路上的双向路段构建。
- 当前明确未启动的扩展方向：
  - 封闭式道路的路段提取
  - 普通道路上的单向路段提取

## 2. 当前正式范围与总约束
- official end-to-end 入口先建立 working Nodes / Roads，再执行 roundabout preprocessing，然后进入 Step1-Step5。
- 后续所有业务判断统一基于 working fields：
  - node：`grade_2`、`kind_2`、`closed_con`
  - road：`road_kind`、`segmentid`、`s_grade`
- 当前双向构段统一正式约束：
  - node：`closed_con in {2,3}`
  - road：`road_kind != 1`
- `raw grade / kind` 只保留为原始输入、审计和展示字段，不再参与后续业务筛选。

## 3. 模块开始阶段

### 3.1 working bootstrap
- 模块开始即复制 raw Nodes / Roads，形成 working layers。
- working nodes 初始化：
  - `grade_2 = grade`
  - `kind_2 = kind`
- working roads 初始化：
  - `s_grade = null`
  - `segmentid = null`
- 后续 Step1-Step5 一律在 working layers 上运行。

### 3.2 roundabout preprocessing
- working bootstrap 后、Step1 前执行环岛预处理。
- 从 working roads 中识别 `roadtype` 含 `bit3 = 8` 的 road。
- 仅按共享 node 的拓扑连通关系聚组，不使用 buffer 或几何近邻。
- 每组规则：
  - 选最小 node id 作为 `mainnode`
  - `mainnode` 写为：
    - `grade_2 = 1`
    - `kind_2 = 64`
  - 组内其他 node 写为：
    - `grade_2 = 0`
    - `kind_2 = 0`
  - 全组 `mainnodeid` 刷为该 `mainnode`
- 环岛 `mainnode` 是受保护语义路口，后续 generic node refresh 必须跳过，不能被改写成其他路口类型。

## 4. 官方 Step1-Step5 映射
1. Step1：候选 Pair 发现，只输出 `pair_candidates`
2. Step2：首轮 `validated / rejected / trunk / segment_body / step3_residual`
3. Step3：基于 Step2 结果刷新 working Nodes / Roads
4. Step4：基于 residual graph 的下一轮构段
5. Step5：`Step5A / Step5B / Step5C` staged residual graph 收尾，并统一刷新

## 5. Step1-3 阶段

### 5.1 业务目标
- Step1-3 是首轮双向路段构建阶段。
- 业务目标是：
  - 从当前工作图中识别首轮合法双向端点对
  - 对 candidate 做 trunk / segment_body / residual 的正式判定
  - 生成首轮构段结果并刷新 working Nodes / Roads，为外层 residual graph 轮次打底

### 5.2 完成任务
- Step1：
  - 发现 `pair_candidates`
  - 不做最终有效性结论
- Step2：
  - 输出 `validated / rejected`
  - 输出 `trunk`
  - 输出 `segment_body`
  - 输出 `step3_residual`
- Step3：
  - 刷新 working Nodes / Roads
  - 将已构出的 `segment_body` 写入 `segmentid / s_grade`
  - 调整 `grade_2 / kind_2`

### 5.3 种子点筛选条件
- 首轮种子点一律从 working nodes 中筛选。
- 基础约束统一为：
  - `closed_con in {2,3}`
  - 节点在当前 working graph 上仍有可用 road
- “全通路口”语义统一接受：
  - `kind_2 in {4,64}`
- “交叉 + 环岛 + T”语义统一接受：
  - `kind_2 in {4,64,2048}`
- 当前官方主线使用 `step1_pair_s2.json`，其默认首轮种子点是满足当前策略配置的高等级全通路口。

### 5.4 终止节点筛选条件
- 首轮终止节点与种子点使用同一套 working-node 规则体系。
- 终止节点也必须满足：
  - `closed_con in {2,3}`
  - 当前 working graph 上仍有可用 road
- 同时叠加历史高等级边界语义：
  - 历史高等级边界 `mainnode` 进入 `terminate`
  - 同时也进入 `hard-stop`

### 5.5 关键实现方案与约束
- Step1 只输出 `pair_candidates`，不代表最终有效 pair。
- Step2 是首轮正式判定内核：
  - `final segment` 只表达当前 validated pair 的 pair-specific road body
  - 弱规则不做硬删，统一进入 `step3_residual`
  - 强规则 A/B/C 保持成立
- 双向构段统一共享两个 50m gate：
  - `MAX_DUAL_CARRIAGEWAY_SEPARATION_M = 50.0`
  - `MAX_SIDE_ACCESS_DISTANCE_M = 50.0`
- trunk / 最小闭环 gate：
  - 用 forward / reverse 两条 polyline 的最大最近距离作为判定值
  - 超限时拒绝理由为 `dual_carriageway_separation_exceeded`
- side component / 旁路 gate：
  - 用 side component geometry 到 trunk geometry 的最大最近距离作为判定值
  - 超限时改入 `step3_residual`
- 所有参与首轮双向构段的 road 都必须满足：
  - `road_kind != 1`

## 6. Step4 阶段

### 6.1 业务目标
- Step4 是 residual graph 第一轮外层构段。
- 业务目标是：
  - 在首轮剔除已构 road 后的 residual graph 上，继续提取下一轮双向路段
  - 将首轮未能闭合但在下一等级输入约束下合法的端点对补出来

### 6.2 完成任务
- 基于 refreshed working Nodes / Roads 构建 Step4 working graph
- 在 residual graph 上执行双向 pair / trunk / segment_body 识别
- 产出 Step4 的 validated pairs、trunk、segment_body 和审计结果

### 6.3 种子点筛选条件
- Step4 种子点来自两部分并集：
  - `Step2` 滚动下来的全量 endpoint pool
  - 当前 Step4 新增满足输入规则的节点
- 当前 Step4 节点正式输入约束：
  - `grade_2 in {1,2}`
  - `kind_2 in {4,64,2048}`
  - `closed_con in {2,3}`
- 端点进入当前轮前，还要满足：
  - 在当前 Step4 working graph 上仍有可用 road

### 6.4 终止节点筛选条件
- Step4 terminate 与 seed 使用同一 endpoint pool 体系。
- 历史高等级边界和上一轮滚动端点同时进入：
  - `terminate`
  - `hard-stop`
- 环岛 `mainnode` 若满足输入规则，按交叉路口同等处理。

### 6.5 关键实现方案与约束
- Step4 工作图必须先剔除：
  - 已有非空 `segmentid` 的 road
  - `road_kind = 1` 的 road
- Step4 复用双向构段内核，因此与 Step2 使用同一套：
  - trunk / 最小闭环 50m 上下行 gate
  - side component 50m 侧向 gate
- Step4 端点滚动不是只传成功 pair 端点，而是传上一轮的全量 endpoint pool。
- 若某端点在当前 working graph 上已无剩余可用 road，会自然退出当前轮。

## 7. Step5A / Step5B / Step5C

### 7.1 Step5A

#### 业务目标
- 在 Step4 之后继续向更低等级扩展双向路段构段。
- 这是 staged residual graph 的第一阶段，用来承接 Step4 之后仍未构出的合法双向段。

#### 完成任务
- 在 Step4 residual graph 上继续构双向 pair
- 输出 Step5A 的 validated pairs、trunk、segment_body、residual

#### 种子点筛选条件
- Step5A 种子点来自：
  - `Step4` 滚动下来的全量 endpoint pool
  - 当前 Step5A 新增满足输入规则的节点
- Step5A 节点输入约束：
  - `closed_con in {2,3}`
  - 且满足：
    - `kind_2 in {4,64,2048}` 且 `grade_2 in {1,2}`
    - 或 `kind_2 in {4,64}` 且 `grade_2 = 3`

#### 终止节点筛选条件
- Step5A terminate 与 seed 使用同一 endpoint pool 体系。
- 历史边界与滚动端点同时进入 `terminate / hard-stop`。

#### 关键实现方案与约束
- Step5A 仍然使用统一双向构段内核。
- 50m trunk gate 与 50m side gate 在该阶段继续生效。
- Step5A 产出的全量 endpoint pool 会继续滚入 Step5B。

### 7.2 Step5B

#### 业务目标
- 在 Step5A 之后继续兜底更低等级、但仍属于当前双向路段语义的构段。

#### 完成任务
- 继续在 residual graph 上提取双向 pair / trunk / segment_body
- 形成 Step5B 阶段输出

#### 种子点筛选条件
- Step5B 种子点来自：
  - `Step5A` 滚动下来的全量 endpoint pool
  - 当前 Step5B 新增满足输入规则的节点
- Step5B 节点输入约束：
  - `closed_con in {2,3}`
  - `kind_2 in {4,64,2048}`
  - `grade_2 in {1,2,3}`

#### 终止节点筛选条件
- Step5B terminate 与 seed 使用同一 endpoint pool。
- 同一批滚动端点仍保留 `hard-stop`，但不因此失去 seed / terminate 身份。

#### 关键实现方案与约束
- Step5B 继承的不是“上一轮 validated pair 成功端点”，而是上一轮全量 endpoint pool。
- 若某端点在当前 working graph 上所有可用 road 已被前序轮次构出并剔除，它会自然退出 Step5B。
- Step5B 继续复用统一的：
  - trunk / 最小闭环 50m gate
  - side component 50m gate

### 7.3 Step5C

#### 业务目标
- Step5C 是当前 staged runner 的最终兜底轮。
- 目标是在不破坏历史边界和已有 segment 的前提下，把前面轮次仍未构出的合法双向段尽可能收口。

#### 完成任务
- 在最终 residual graph 上执行最后一轮双向 pair / trunk / segment_body 判定
- 输出 Step5C 结果，并进入统一 refresh

#### 种子点筛选条件
- Step5C 种子点来自：
  - `Step5B` 滚动下来的全量 endpoint pool
  - 当前 Step5C 新增满足输入规则的节点
- Step5C 节点输入约束：
  - `closed_con in {2,3}`
  - `kind_2 in {1,4,64,2048}`
  - `grade_2 in {1,2,3}`

#### 终止节点筛选条件
- Step5C terminate 与 seed 继续使用同一 endpoint pool。
- 历史边界、滚动端点和当前轮合法端点都可作为最终兜底端点。
- 这些端点仍然同时保留 `hard-stop`，不允许被继续穿越。

#### 关键实现方案与约束
- Step5C 不是局部兜底，而是承接 Step2 -> Step4 -> Step5A -> Step5B 全链路滚动下来的 endpoint pool。
- 该阶段仍使用统一的：
  - trunk / 最小闭环 50m gate
  - side component 50m gate
- Step5A / Step5B / Step5C 之间：
  - 只剔除已构成的 `segment_body` road
  - 不刷新属性
- Step5 全部结束后统一刷新：
  - `grade_2`
  - `kind_2`
  - `s_grade`
  - `segmentid`

## 8. 当前 T01 模块输出结果与业务含义

### 8.1 最终输出
- official runner 当前最终输出：
  - `nodes.geojson`
  - `roads.geojson`
  - `validated_pairs_skill_v1.csv`
  - `segment_body_membership_skill_v1.csv`
  - `trunk_membership_skill_v1.csv`
  - `skill_v1_manifest.json`
  - `skill_v1_summary.json`

### 8.2 业务含义
- `nodes.geojson`
  - 表达当前 working node 语义结果
  - 其中 `grade_2 / kind_2 / mainnodeid` 已被逐轮更新
- `roads.geojson`
  - 表达当前 working road 语义结果
  - 其中 `segmentid / s_grade` 表示 road 已归属到哪个双向路段
- `validated_pairs_skill_v1.csv`
  - 表达最终被确认为合法双向路段端点对的集合
- `segment_body_membership_skill_v1.csv`
  - 表达每个合法 pair 的 pair-specific road body
- `trunk_membership_skill_v1.csv`
  - 表达每个合法 pair 用于成立最小闭环或主骨架判定的 trunk roads

## 9. 当前活动基线冻结
- 当前活动基线不再是旧的单样例 `XXXS freeze`。
- 当前活动基线已经切换为三样例套件：
  - `modules/t01_data_preprocess/baselines/t01_skill_active_three_sample_suite/XXXS/`
  - `modules/t01_data_preprocess/baselines/t01_skill_active_three_sample_suite/XXXS2/`
  - `modules/t01_data_preprocess/baselines/t01_skill_active_three_sample_suite/XXXS3/`
- 三组样例的业务定位：
  - `XXXS`：通用冒烟
  - `XXXS2`：重点覆盖上下行 / 侧向距离 gate
  - `XXXS3`：重点覆盖环岛预处理
- 后续性能优化、结构重构或实现调整，必须同时对齐这三组活动基线。
- 任一样例结果与当前活动基线不一致，默认都需要用户复核后再决策是否接受变更。

## 10. 历史归档基线
- 旧单样例 freeze 继续保留为归档历史：
  - `modules/t01_data_preprocess/baselines/t01_skill_v1_0_xxxs/`
- 旧语义修正候选 freeze 继续保留为历史候选：
  - `modules/t01_data_preprocess/baselines/t01_skill_v1_0_xxxs_semantic_fix_candidate/`
- 它们不再作为当前活动基线，但仍可用于追溯差异来源。

## 11. 当前性能口径

### 11.1 当前已知阶段级热点
- A200 全量运行下，`Step2` 是当前绝对主瓶颈。
- `Step4` 与 `Step5` 次之，但二者当前仍明显受同一双向构段内核影响。
- `debug=true` 会显著增加导出与审计 I/O 成本，但不改变最终业务结果。

### 11.2 当前正式性能约束
- 所有后续性能优化都必须同时对齐当前活动三样例基线：
  - `XXXS`
  - `XXXS2`
  - `XXXS3`
- 若任一样例结果与活动基线不一致，必须先产出差异审计，再由用户确认是否接受。
- 性能优化不得通过修改当前 accepted 业务语义换取速度。

### 11.3 当前首轮已落地优化
- `Step2` validated 流程复用首轮已算出的 `segment_body_candidate_road_ids / cut_infos`，不再在 tighten 阶段重复 `_refine_segment_roads(...)`。
- trunk validation 构建 directed adjacency 时，不再按 pair 全量扫描 `context.directed`，而是仅遍历当前 `allowed_road_ids`。
- 以上优化自动作用于复用同一双向构段内核的：
  - `Step2`
  - `Step4`
  - `Step5A`
  - `Step5B`
  - `Step5C`
