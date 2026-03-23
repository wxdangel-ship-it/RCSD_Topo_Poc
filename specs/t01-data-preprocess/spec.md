# T01 数据预处理规格

## 1. 当前正式目标
- T01 当前正式流程面向普通道路双向 Segment 构建。
- 官方流程统一为：`working bootstrap -> roundabout preprocessing -> Step1 -> Step2 -> Step3(refresh) -> Step4 -> Step5A -> Step5B -> Step5C -> Step6`。
- Step6 已正式纳入 end-to-end 主流程，不再视为额外 POC 尾处理。

## 2. 官方输入与输出契约

### 2.1 官方输入
- 官方推荐输入统一为：
  - `nodes.geojson`
  - `roads.geojson`
- Shapefile 仅保留读取兼容层，不再作为官方输入契约、官方示例命令或官方推荐用法。

### 2.2 正式业务字段
- node 侧正式业务判断字段：
  - `grade_2`
  - `kind_2`
  - `closed_con`
  - `working_mainnodeid`
- road 侧正式输出字段：
  - `segmentid`
  - `sgrade`
- `s_grade`、`segment_id`、`Segment_id` 仅允许在读取兼容层中被识别，不再作为新输出正式字段。
- 对外公开 node 图层不显式输出 `working_mainnodeid`；该字段保留为内部 working 语义字段。

## 3. 开始阶段

### 3.1 working bootstrap
- 模块开始阶段即复制 raw `nodes / roads` 并生成 working layers。
- working node 初始化：
  - `grade_2 = grade`
  - `kind_2 = kind`
  - `working_mainnodeid = mainnodeid`
- `working_mainnodeid` 作为内部 working 语义字段继续维护并供后续步骤优先使用
- 默认不改 raw `mainnodeid`；但在环岛预处理中，允许将聚合成环岛的一组 node 的 `mainnodeid / working_mainnodeid` 统一修正到环岛 `mainnode`
- working road 初始化：
  - `sgrade = null`
  - `segmentid = null`

### 3.2 roundabout preprocessing
- roundabout preprocessing 位于 bootstrap 之后、Step1 之前。
- 环岛 `mainnode` 在 working 层上写成：
  - `grade_2 = 1`
  - `kind_2 = 64`
- 环岛 member node 写成：
  - `grade_2 = 0`
  - `kind_2 = 0`
- 环岛全组 node 同步写成：
  - `mainnodeid = roundabout mainnode`
  - `working_mainnodeid = roundabout mainnode`
- 环岛 `mainnode` 在后续 refresh 中受保护。
- 环岛是当前唯一允许显式修正公开 `mainnodeid` 的场景。

## 4. Step1-Step5C accepted 业务口径
- Step1 只输出 `pair_candidates`。
- Step2 输出：
  - `validated / rejected`
  - `trunk`
  - `segment_body`
  - `step3_residual`
- Step4 / Step5A / Step5B / Step5C 继续采用 staged residual graph。
- Step5C 保持 `adaptive barrier fallback`，Step5A / Step5B 仍为 strict。
- 当前双向构段统一前置过滤：
  - node：`closed_con in {2,3}`
  - road：`road_kind != 1`
- 右转专用道约束：
  - `formway bit7` 的右转专用道不进入 Step1-Step5 的 Segment 构建图
  - 若节点去除右转专用道后不再构成真实路口，则该节点不得作为构段路口、through 路口或 residual graph boundary
  - 因而不得以“挂接右转专用道的路口仍是 through 硬切断点”作为业务规则
  - `kind_2 = 1` 若仅由右转专用道挂接产生，不得作为正式路口进入构段
- 当前双向构段统一 gate：
  - `MAX_DUAL_CARRIAGEWAY_SEPARATION_M = 50.0`
  - `MAX_SIDE_ACCESS_DISTANCE_M = 50.0`
- Step2 单侧旁路系统的保留口径：
  - 只允许“单向且与主路平行”的 side corridor / bypass system 继续留在 `segment_body`
  - 若 non-trunk component 含任意双向 side road，即使 attachment flow 与 parallel corridor 其余指标满足，也不得视为合法单侧旁路
  - 此类 component 统一转入 `step3_residual`
- Step2 / Step4 / Step5 全阶段 T 型路口前置门禁：
  - 若某个 trunk candidate 属于 `bidirectional_minimal_loop`
  - 且内部路径表现为“弱 connector node 串接 + 内部 T-support / support anchor 闭合”
  - 则该 pair 在 `single-pair validation` 直接以 `t_junction_vertical_tracking_blocked` 拒绝
  - 只要该 T 型路口不是 segment 起点 / 终点，该规则在 Step2 / Step4 / Step5A / Step5B / Step5C 都必须生效
  - 该类 pair 不进入 same-stage pair arbitration，也不得在后续阶段重新构出

## 5. Step6 正式纳入后的定义

### 5.1 定位
- Step6 是 road-level `segmentid` 结果的正式 segment-level 聚合与语义审计阶段。
- Step6 不重新做构段搜索，只消费 Step5C 之后的最新 refreshed `nodes / roads`。
- 在 official runner 中，Step6 优先复用 Step5 的内存态 `nodes / roads`、`mainnode group` 和 `group_to_allowed_road_ids`，避免重复读取与重复分组。

### 5.2 语义路口规则
- Step6 所有语义路口判断统一使用：
  - official runner 内存态优先使用 `working_mainnodeid`
  - 公开 `nodes.geojson` 中若未显式带出 `working_mainnodeid`，则回退 `mainnodeid`
  - 再为空时回退 node 自身 `id`
- Step6 不使用 raw `grade / kind` 做路口类型判断。

### 5.3 Step6 输出
- official end-to-end 在 `debug=false` 时，至少输出：
  - `nodes.geojson`
  - `roads.geojson`
  - `segment.geojson`
  - `inner_nodes.geojson`
  - `segment_error.geojson`
  - `segment_error_s_grade_conflict.geojson`
  - `segment_error_grade_kind_conflict.geojson`
  - `t01_skill_v1_summary.json`
- Step6 standalone 入口仍保留，便于单独调试与审计。

### 5.4 Segment 聚合
- 仅聚合 `roads.segmentid` 非空的 road。
- 每个唯一 `segmentid` 生成一条 `segment.geojson` 记录。
- `segment.geojson.geometry` 统一输出 `MultiLineString`。
- `pair_nodes` 由 `segmentid` 直接解析：
  - `A_B -> A,B`
  - `A_B_N -> A,B`
- `junc_nodes` 记录仍向当前 Segment 之外分支的语义路口。
- 若某语义路口的全部允许 road 都属于当前 Segment，则该路口不写入 `junc_nodes`，而是把该组全部 node 完整复制到 `inner_nodes.geojson`，仅附加 `segmentid` 追溯字段。
- `inner_nodes.geojson` 不显式输出 `working_mainnodeid`。

### 5.5 Segment 级规则
- 规则 1：若 `pair_nodes` 两端语义路口 `grade_2` 均为 `1`，且当前 `sgrade != "0-0双"`，则 Step6 将该 Segment 的 `sgrade` 轻调整为 `"0-0双"`。
- 规则 2：若最终 `sgrade = "0-0双"`，且其中间 `junc_nodes` 存在 `grade_2 = 1 且 kind_2 = 4`，则输出到：
  - `segment_error.geojson`
  - `segment_error_grade_kind_conflict.geojson`
- 同一 `segmentid` 下若出现多个 `sgrade`，则：
  - 按 `0-0双 > 0-1双 > 0-2双` 选高等级写入 `segment.geojson`
  - 同时输出到：
    - `segment_error.geojson`
    - `segment_error_s_grade_conflict.geojson`

## 6. 官方入口与调试入口

### 6.1 官方 end-to-end
```bash
python -m rcsd_topo_poc t01-run-skill-v1 \
  --road-path <roads.geojson> \
  --node-path <nodes.geojson> \
  --out-root <out_root>
```

### 6.2 分步 / 调试入口
- `t01-step1-pair-poc`
- `t01-step2-segment-poc`
- `t01-s2-refresh-node-road`
- `t01-step4-residual-graph`
- `t01-step5-staged-residual-graph`
- `t01-step6-segment-aggregation-poc`

## 7. freeze compare 口径
- compare 仍以业务结果一致性为主：
  - `validated_pairs`
  - `segment_body_membership`
  - `trunk_membership`
  - refreshed `nodes / roads` 语义 hash
- 对 roads schema 迁移：
  - baseline 的 `s_grade`
  - current 的 `sgrade`
  通过语义归一化比较，不误判为业务回退。
- 仅 schema 差异记为 `SCHEMA_MIGRATION_DIFFERENCE`，不直接判定业务 FAIL。

## 8. 性能优化目标
- Step6 正式纳入后，必须避免与 Step1-Step5C 重复做以下工作：
  - 重复读取 refreshed `nodes / roads`
  - 重复按 `working_mainnodeid` 分组
  - 重复构建 node-road incidence
  - `debug=false` 下重复写盘大型中间层
- 当前正式优化口径：
  - official runner 中 Step6 复用 Step5 的内存态 records
  - Step6 复用 Step5 已构建的 `mainnode_groups`
  - Step6 复用 Step5 已构建的 `group_to_allowed_road_ids`
  - Step5 的别名 refreshed 输出仅在 `debug=true` 下保留

## 9. Step2 同阶段合法 pair 冲突仲裁

### 9.1 业务定义
- 单 pair 通过 Step2 硬合法性校验，只能说明其自身合法，不代表其在同阶段 corridor 竞争中一定应被最终保留。
- Step2 当前新增 same-stage pair arbitration：先收集单 pair 合法候选，再在同阶段 conflict component 内做仲裁，最后才固化 `validated_pairs_final / segment_body / step3_residual`。

### 9.2 conflict component
- 若两个合法 pair 在以下任一层面发生竞争，则视为冲突：
  - `trunk_road_ids` overlap
  - `segment_body candidate / segment_body` overlap
  - 关键 corridor roads overlap
- Step2 先构建 pair-level conflict graph，再按连通分量提取 `conflict components`。
- 仲裁仅在每个 component 内局部进行，不引入全局网络级优化器。

### 9.3 仲裁对象
- 仲裁对象不是裸 `pair_id`，而是：
  - `single-pair legal pair`
  - 加上其 `trunk / segment_body candidate` 组合
- 也就是说，最终保留结果同时考虑：
  - pair 是否合法
  - corridor 是否更自然地归属于该 pair
  - 该 pair 对最终 `segment_body` 的支撑是否更完整

### 9.4 当前优选维度
- `contested_trunk_coverage_count / contested_trunk_coverage_ratio`
- `endpoint_boundary_penalty`
- `internal_endpoint_penalty`
- `body_connectivity_support`
- `semantic_conflict_penalty`
- `strong_anchor_win_count`
- 若仍打平，再使用稳定可复现的 tie-break（当前实现使用稳定字典序）

### 9.5 solver 口径
- 小型 component 使用 exact 组合搜索。
- 大型 component 可降级为 fallback greedy，但必须在审计中显式记录：
  - `exact_solver_used`
  - `fallback_greedy_used`
- 当前仲裁目标是显著摆脱“固定顺序先到先得”，而不是一次性引入全局最优求解器。

### 9.6 XXXS7 作为定点样例
- `S2:1019883__1026500`
- `S2:1026500__1026503`
- `500588029`
- 该组样例用于验证：在两个 pair 均合法时，Step2 能否表达“`500588029` 更自然归属于 `1026500__1026503`”。
