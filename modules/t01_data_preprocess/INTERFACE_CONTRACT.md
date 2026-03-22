# T01 - INTERFACE_CONTRACT

## 1. 文档状态
- 状态：`accepted baseline contract / current active baseline`
- 用途：固化当前 working layer、roundabout preprocessing、Step1-Step6、freeze compare 与 Step6 输出契约

## 2. 官方输入契约
- 官方推荐输入统一为：
  - `nodes.geojson`
  - `roads.geojson`
- Shapefile 仅保留读取兼容层，不再作为官方契约或官方示例。

## 3. Working layers

### 3.1 Working Nodes
- 必备字段：
  - `id`
  - `mainnodeid`
  - `working_mainnodeid`
  - `closed_con`
  - `grade`
  - `kind`
  - `grade_2`
  - `kind_2`
- 初始化：
  - `grade_2 = grade`
  - `kind_2 = kind`
  - `working_mainnodeid = mainnodeid`
- 默认情况下，`mainnodeid` 保持原始输入值，运行期主节点语义统一写入 `working_mainnodeid`
- 例外：在 `roundabout preprocessing` 中，聚合成环岛的一组 node 允许同步改写 `mainnodeid` 与 `working_mainnodeid`，统一指向环岛 `mainnode`

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
- 读取兼容层允许识别：
  - `s_grade`
  - `segment_id`
  - `Segment_id`
- 新输出不得再写上述 legacy 字段

## 4. 正式业务字段
- Step1-Step6 业务判断统一使用：
  - node：`grade_2 / kind_2 / closed_con / working_mainnodeid`
  - road：`segmentid / sgrade / road_kind`
- raw `grade / kind` 只保留输入、展示与审计作用。

## 5. 开始阶段

### 5.1 bootstrap
- official runner 进入模块后先建立 working `nodes / roads`

### 5.2 roundabout preprocessing
- bootstrap 后、Step1 前执行
- 环岛 `mainnode`：
  - `grade_2 = 1`
  - `kind_2 = 64`
- 环岛 member node：
  - `grade_2 = 0`
  - `kind_2 = 0`
- 环岛全组 node：
  - `mainnodeid = roundabout mainnode`
  - `working_mainnodeid = roundabout mainnode`
- 环岛 `mainnode` 在后续 refresh 中受保护

## 6. Step1-Step5C accepted 契约
- Step1：只输出 `pair_candidates`
- Step2：输出 `validated / rejected / trunk / segment_body / step3_residual`
- Step4、Step5A、Step5B：strict staged residual graph
- Step5C：adaptive barrier fallback
- 全流程统一前置过滤：
  - node：`closed_con in {2,3}`
  - road：`road_kind != 1`
- 全流程统一 gate：
  - `MAX_DUAL_CARRIAGEWAY_SEPARATION_M = 50.0`
  - `MAX_SIDE_ACCESS_DISTANCE_M = 50.0`

## 7. Step5C 契约

### 7.1 输入与中间集合
- `rolling endpoint pool`
- `protected hard-stop set`
- `demotable endpoint set`
- `actual terminate barriers`

### 7.2 当前 accepted 口径
- `rolling endpoint pool`
  - 历史 endpoint mainnode
  - 加上当前 residual graph 上满足：
    - `closed_con in {2,3}`
    - `kind_2 in {4,64,2048}`
    - `grade_2 in {1,2,3}`
    的语义节点
  - `kind_2 = 1` 不得仅因字段条件进入 pool
- `protected hard-stop set`
  - 当前只保留环岛 mainnode：`kind_2 = 64` 且 `closed_con in {2,3}`
- `demotable endpoint set`
  - `rolling endpoint pool - protected hard-stop set`
  - 当前最小 accepted 判据：
    - `semantic incident degree = 2`
    - `distinct neighbor semantic groups = 2`
- `actual terminate barriers`
  - `protected hard-stop set`
  - 加上当前 residual graph 上未被 demote 的真实 barrier endpoint

### 7.3 Step5C 审计输出
- `step5c_rolling_endpoint_pool.csv/.geojson`
- `step5c_protected_hard_stops.csv/.geojson`
- `step5c_demotable_endpoints.csv/.geojson`
- `step5c_actual_barriers.csv/.geojson`
- `step5c_endpoint_demote_audit.json`
- `target_pair_audit_997356__39546395.json`

## 8. Step6 正式输出契约

### 8.1 输入
- latest refreshed `nodes.geojson / roads.geojson`
- Step6 不重新做构段搜索
- Step6 使用 `working_mainnodeid`，为空时回退 node `id`

### 8.2 输出
- `segment.geojson`
- `inner_nodes.geojson`
- `segment_error.geojson`
- `segment_error_s_grade_conflict.geojson`
- `segment_error_grade_kind_conflict.geojson`
- `segment_summary.json`
- `segment_build_table.csv`
- `inner_nodes_summary.json`

### 8.3 语义
- `segment.geojson`
  - `id = segmentid`
  - `sgrade`
  - `pair_nodes`
  - `junc_nodes`
  - `roads`
- `pair_nodes`
  - `A_B -> A,B`
  - `A_B_N -> A,B`
- `inner_nodes.geojson`
  - 完整复制被某个 Segment 完全内含的 node 原字段
  - 仅追加 `segmentid`
- `segment_error.geojson`
  - 总错误图层
- `segment_error_s_grade_conflict.geojson`
  - 仅记录 `error_type = s_grade_conflict`
- `segment_error_grade_kind_conflict.geojson`
  - 仅记录 `error_type = grade_kind_conflict`

### 8.4 Step6 规则
- 规则 1：若 segment 两端 `pair_nodes` 的 `grade_2` 均为 `1`，且当前 `sgrade != "0-0双"`，则将该 Segment 的 `sgrade` 轻调整为 `"0-0双"`
- 规则 2：若最终 `sgrade = "0-0双"`，且其中间 `junc_nodes` 出现 `grade_2 = 1 且 kind_2 = 4`，则输出到 `segment_error.geojson` 与 `segment_error_grade_kind_conflict.geojson`
- 若同一 `segmentid` 下存在多个 `sgrade`，则按 `0-0双 > 0-1双 > 0-2双` 选高等级写入 `segment.geojson`，并同时输出到 `segment_error.geojson` 与 `segment_error_s_grade_conflict.geojson`

## 9. 官方 end-to-end 输出
- `nodes.geojson`
- `roads.geojson`
- `segment.geojson`
- `inner_nodes.geojson`
- `segment_error.geojson`
- `segment_error_s_grade_conflict.geojson`
- `segment_error_grade_kind_conflict.geojson`
- `validated_pairs_skill_v1.csv`
- `segment_body_membership_skill_v1.csv`
- `trunk_membership_skill_v1.csv`
- `skill_v1_manifest.json`
- `skill_v1_summary.json`

## 10. freeze compare 契约
- compare 重点仍是业务结果一致性：
  - `validated_pairs`
  - `segment_body_membership`
  - `trunk_membership`
  - refreshed `nodes / roads` 语义 hash
- roads compare 必须兼容：
  - baseline `s_grade`
  - current `sgrade`
- 若只有 schema 迁移差异，应标记为 `SCHEMA_MIGRATION_DIFFERENCE`，不能误报业务 FAIL
