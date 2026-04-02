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

## 2.1 官方 runner / 诊断契约
- 官方 end-to-end 入口：
  - `python -m rcsd_topo_poc t01-run-skill-v1`
- 官方 continuation 入口：
  - `python -m rcsd_topo_poc t01-continue-oneway-segment`
- 官方 freeze compare 入口：
  - `python -m rcsd_topo_poc t01-compare-freeze`
- debug 默认值：
  - `t01-run-skill-v1`、`t01-continue-oneway-segment` 与 `t01-step6-segment-aggregation-poc` 默认 `debug=false`
  - `t01-step1-pair-poc / t01-step2-segment-poc / t01-s2-refresh-node-road / t01-step4-residual-graph / t01-step5-staged-residual-graph` 默认 `debug=true`
- `debug` 只允许影响：
  - 中间 stage 目录
  - 审计图层
  - progress / perf 诊断产物
- `debug` 不得改变最终业务结果：
  - `validated_pairs_skill_v1.csv`
  - `segment_body_membership_skill_v1.csv`
  - `trunk_membership_skill_v1.csv`
  - `segment.gpkg`
- `t01-run-skill-v1` 的稳定诊断产物：
  - `t01_skill_v1_progress.json`
  - `t01_skill_v1_perf.json`
  - `t01_skill_v1_perf.md`
  - `t01_skill_v1_perf_markers.jsonl`
  - `distance_gate_scope_check.json`
  - `all_stage_segment_roads/`
- `trace_validation_pair_ids`：
  - 仅作为 Step2 progress / perf trace 透传参数
  - 不是业务输入
  - 不得改变 candidate search、validated_pairs、segment_body、endpoint pool 与最终 `segment.gpkg` 语义
- `stop_after_step2_validation_pair_index`：
  - 仅用于 Skill v1 全链路诊断截停
  - 不改变已执行阶段的业务语义

- `t01-continue-oneway-segment`：
  - `--continue-from-dir` 允许三类输入：
    - 之前完整 `t01-run-skill-v1` out_root，且包含 `debug/step5/`
    - 直接的 `debug/` 目录，且同时含 `step2/step4/step5/`
    - 直接的 `Step5` refreshed 输出目录，且包含 Step5 marker 与 `nodes.gpkg/roads.gpkg`
  - continuation 模式只执行 `oneway + Step6`
  - 不回退重跑 `Step1-Step5`
  - `--out-root` 必须是新的结果目录，不得与 source dir 或解析出的 `Step5` stage dir 重叠
  - `--compare-freeze-dir` 仅在输入是完整 `Skill v1` out_root 或完整 `debug/` 目录且同时含 `step2/step4/step5/` 时允许使用

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
- working bootstrap 的执行顺序为：
  - working field 初始化
  - roundabout preprocessing
  - bootstrap node retyping
  - 再进入 Step1
- 环岛 `mainnode`：
  - `grade_2 = 1`
  - `kind_2 = 64`
- 环岛 member node：
  - `grade_2 = 0`
  - `kind_2 = 0`
- 该组所有 node 的 `mainnodeid` 统一写为环岛 `mainnode`。
- 环岛 `mainnode` 后续不参与 generic node 刷新。

### 4.2 bootstrap node retyping
- 仅允许修改 working node 的：
  - `grade_2`
  - `kind_2`
- 不修改原始：
  - `grade`
  - `kind`
- 当前 bootstrap 只支持极窄的 strict-T 纠错：
  - 当前节点为 `grade_2 = 1, kind_2 = 4`
  - `total_neighbor_family_count = 3`
  - `segment_neighbor_family_count = 0`
  - `residual_neighbor_family_count = 3`
  - 仅存在 `1` 个 through family，且其代表节点为 `grade_2 = 1, kind_2 = 4`
  - 两个 side family 都必须是单 road family，且满足：
    - 一个 side family 的代表节点为 `grade_2 = 1, kind_2 = 4`
    - 一个 side family 的代表节点为 `kind_2 = 2048` 且 `grade_2 >= 2`
- 命中时才允许：
  - `grade_2 = 2`
  - `kind_2 = 2048`
- 当前 bootstrap 不做：
  - `1/4 -> 2/4`
  - `1/4 -> 3/2048`

### 4.3 右转专用道契约
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
  4. 唯一 segment + 其余非segment road 同时存在 `in/out` 时，执行 family-based retyping：
     - 仅对当前 `grade_2 = 1, kind_2 = 4` 生效
     - `total_neighbor_family_count = 3`
     - `segment_neighbor_family_count = 1`
     - `residual_neighbor_family_count = 2`
     - 若两个 residual family 都是 `simple_residual_family`，则改为 `grade_2 = 2, kind_2 = 2048`
     - 否则改为 `grade_2 = 2, kind_2 = 4`
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

### 5.9 Step5 后单向补段
- 执行位置：
  - 在 `Step5C` refreshed `nodes / roads` 之后
  - 在 `Step6` 聚合之前
- 作用边界：
  - 仅补齐仍未被双向 Segment 构成的单向 road
  - 不回写 `Step2 / Step4 / Step5A / Step5B / Step5C` 的双向构段规则
- 共享过滤：
  - `road_kind != 1`
  - `formway != 128`
  - 右转专用道不参与
  - 已有非空 `segmentid` 的 road 不再进入单向阶段
- 业务判断统一使用：
  - `kind_2`
  - `grade_2`
- through 规则：
  - 二度链接节点不切段
  - 非当前 terminate 的语义路口允许 through
  - 仅在命中当前轮 terminate 时切段停止
- 多分支延展：
  - 当前节点未命中 terminate 时，候选前进 road 中仅选择与当前行进方向夹角最小的一条继续
- 阶段定义：
  - `0-0单`：`closed_con in {1,3}`、`kind_2 in {8,16}`、`grade_2 = 1`
  - `0-1单`：`closed_con in {2,3}`、`kind_2 in {4,8,16,64,2048}`、`grade_2 in {1,2}`
  - `0-2单`：`closed_con in {2,3}`、`kind_2 in {4,8,16,64,2048}`、`grade_2 in {1,2,3}`
- 新构成 road：
  - `sgrade = 0-0单 / 0-1单 / 0-2单`
- 新增 runner 对外产物：
  - `oneway_segment_roads.gpkg`
  - `oneway_segment_build_table.csv`
  - `oneway_segment_summary.json`
  - `unsegmented_roads.gpkg`
  - `unsegmented_roads.csv`
  - `unsegmented_roads_summary.json`
- `unsegmented_roads.*` 口径：
  - 统计双向 + 单向全部阶段完成后仍未形成 Segment 的 road
  - 必须排除 `formway = 128`

## 6. Step6 契约

### 6.1 输入
- 最新 refreshed `nodes.gpkg`
- 最新 refreshed `roads.gpkg`

### 6.2 输出
- `segment.gpkg`
- `inner_nodes.gpkg`
- `segment_error.gpkg`
- `segment_error_s_grade_conflict.gpkg`
- `segment_error_grade_kind_conflict.gpkg`

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
  - 但 `sgrade in {0-0单,0-1单,0-2单}` 的单向 Segment 不适用该提升规则
- 规则2：
  - 对所有 `sgrade = 0-0双` 的 Segment，若其中间 `junc_nodes` 存在：
    - `grade_2 = 1`
    - 且 `kind_2 = 4`
    则输出到 `segment_error.gpkg`
- typed error layers：
  - `segment_error_s_grade_conflict.gpkg` 仅包含 `sgrade` 冲突类记录
  - `segment_error_grade_kind_conflict.gpkg` 仅包含 `grade/kind` 冲突类记录
- Step6 对 `junc_nodes / inner_nodes / segment_error` 的判断，应与全局 `formway != 128` 约束保持一致。

## 7. Freeze Compare 契约
- 当前 active non-regression baseline：
  - `modules/t01_data_preprocess/baselines/t01_skill_active_eight_sample_suite/`
- 在引入 Step5 后单向补段后，freeze compare 的主用途是守护既有双向 Segment accepted baseline：
  - `validated_pairs_skill_v1.csv`
  - `segment_body_membership_skill_v1.csv`
  - `trunk_membership_skill_v1.csv`
  - Step5 结束时、进入单向补段之前的 refreshed `nodes / roads` hash
- 最终运行目录中的 `nodes.gpkg / roads.gpkg / segment.gpkg` 可以包含新增单向 Segment 结果；这些结果不作为双向 baseline compare 的主判定对象。
- 未经用户明确认可，不得更新 active freeze baseline

## 8. 文档与实现边界
- 本契约只描述当前 accepted baseline 下的对外契约与阶段约束。
- 临时样例基线与结构整改进度不写入本契约正文。
- 若实现与本契约冲突，应先修实现或提交歧义说明，不得自行覆盖 accepted baseline。
