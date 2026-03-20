# T01 - INTERFACE_CONTRACT

## 1. 文档状态
- 状态：`accepted baseline contract / Skill v1.0.0`
- 用途：固化当前输入约束、输出契约、分阶段关系与 freeze compare 约束

## 2. 基础输入契约

### 2.1 Road
- 支持：`Shp` / `GeoJSON`
- 必要字段：
  - `id`
  - `snodeid`
  - `enodeid`
  - `direction`
  - `formway`
- 多轮依赖字段：
  - `segmentid`
  - `s_grade`

### 2.2 Node
- 支持：`Shp` / `GeoJSON`
- 必要字段：
  - `id`
  - `kind`
  - `grade`
  - `closed_con`
  - `mainnodeid`
- 多轮依赖字段：
  - `grade_2`
  - `kind_2`

### 2.3 语义路口
- `mainnodeid` 有值时，该值是语义路口 ID
- `mainnodeid` 为空时，node 自身 `id` 是语义路口 ID
- `mainnodeid = NULL` 的单点路口仍是合法 mainnode

## 3. trunk / direction 契约
- `direction = 0 / 1` 的双向 road 视为两条方向相反的可通行 road
- trunk 以语义路口为单元，不只依赖纯几何闭环
- 当前 trunk 支持：
  - 双向直连镜像最小闭环
  - split-merge 混合通道
  - semantic-node-group closure

## 4. Step1 / Step2 契约

### 4.1 Step1
- 输出：`pair_candidates`
- 不代表最终有效 pair

### 4.2 Step2
- 输出：
  - `validated_pairs`
  - `rejected_pair_candidates`
  - `trunk_roads`
  - `segment_body_roads`
  - `step3_residual_roads`
  - `pair_validation_table`
  - `segment_summary.json`
- `segment_body_roads` 只表达当前 validated pair 的 pair-specific road body
- Step2 强规则 A / B / C 固化

## 5. refreshed Node / Road 契约

### 5.1 Node
- 输出字段：
  - `grade_2`
  - `kind_2`
- 语义：
  - 当前滚动语义字段
  - 原始 `grade / kind` 不覆盖
- 刷新优先级遵循 accepted baseline

### 5.2 Road
- 输出字段：
  - `segmentid`
  - `s_grade`
- 已有非空 `segmentid / s_grade` 的 road 后续轮次保持原值不动

## 6. Step4 / Step5 staged 契约

### 6.1 Step4
- 输入：
  - refreshed `nodes.geojson / roads.geojson`
  - `grade_2 in {1,2}`
  - `kind_2 in {4,2048}`
  - `closed_con in {1,2}`
- 工作图：
  - 剔除已有非空 `segmentid` 的 road
- 历史边界：
  - `S2` 端点并入 `seed / terminate / hard-stop`
- 输出：
  - `step4_*`
  - refreshed `nodes.geojson / roads.geojson`

### 6.2 Step5A
- 输入：
  - `closed_con in {1,2}`
  - 且：
    - `kind_2 in {4,2048}` 且 `grade_2 in {1,2}`
    - 或 `kind_2 = 4` 且 `grade_2 = 3`
- 工作图：
  - 剔除历史 `segmentid` road
- 历史边界：
  - `S2 + Step4`

### 6.3 Step5B
- 在 Step5A residual graph 上运行
- 输入：
  - `closed_con in {1,2}`
  - `kind_2 in {4,2048}`
  - `grade_2 in {1,2,3}`
- 只剔除 Step5A 新 `segment_body` road
- 不刷新属性
- `S2 + Step4` 历史边界并入 `seed / terminate`
- Step5A 新端点只做 `hard-stop`

### 6.4 Step5C
- 在 Step5B residual graph 上运行
- 输入：
  - `closed_con in {1,2}`
  - `kind_2 in {1,4,2048}`
  - `grade_2 in {1,2,3}`
- 只剔除 Step5B 新 `segment_body` road
- 不刷新属性
- `S2 + Step4` 历史边界并入 `seed / terminate`
- Step5A / Step5B 新端点只做 `hard-stop`

### 6.5 Step5 统一刷新
- Step5A / Step5B / Step5C 结束后统一刷新：
  - `grade_2 / kind_2 / s_grade / segmentid`

## 7. 官方 end-to-end 契约
- 官方入口：`t01-run-skill-v1`
- 默认 `debug=true`
- 默认输出：
  - 最终 refreshed `nodes.geojson`
  - 最终 refreshed `roads.geojson`
  - `t01_skill_v1_summary.*`
  - 当前轻量 bundle
  - 指定 compare 时的 `freeze_compare_report.*`
- `debug=true` 时，保留分阶段中间结果
- `debug=false` 时，stage 目录使用临时目录串联，不改变最终业务结果

## 8. 性能 / 内存 / 并发边界
- 当前正式纳入的优化：
  - Step1 / Step2 / refresh / Step4 / Step5 输入图层使用固定 2 worker 并行读取
  - 官方 runner 在每个阶段后执行 `gc.collect()`
  - 官方 runner 记录阶段级 `tracemalloc` 峰值内存
  - `debug=false` 时只保留最终结果与轻量审计包
- 当前未纳入的能力：
  - 完整全内存流水线
  - pair / trunk / validated 核心业务决策层的并发执行

## 9. Freeze compare 契约
- 对比入口：`t01-compare-freeze`
- 当前冻结基线：
  - `modules/t01_data_preprocess/baselines/t01_skill_v1_0_xxxs/`
- 对比范围至少包括：
  - validated pair
  - segment_body membership
  - trunk membership
  - refreshed nodes hash
  - refreshed roads hash
- 判定：
  - 全部一致：`PASS`
  - 任一不一致：`FAIL`

## 10. 内网测试交付契约
- 进入内网测试时，默认交付：
  1. 当前分支内网下拉命令
  2. 可直接执行的内网脚本
  3. 可直接执行的关键信息回传命令
- 在上下文已充分时，这三项命令必须可直接执行
