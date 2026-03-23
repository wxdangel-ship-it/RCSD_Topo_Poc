# T01 数据预处理模块

## 当前状态
- 当前正式版本：`T01 Skill v1.0.0`
- official 完整流程：
  - `working bootstrap -> roundabout preprocessing -> Step1 -> Step2 -> Step3(refresh) -> Step4 -> Step5A -> Step5B -> Step5C -> Step6`
- Step6 已正式纳入 official end-to-end，不再是附加 POC。

## 官方输入
- 官方推荐输入统一为 GeoJSON：
  - `nodes.geojson`
  - `roads.geojson`
- Shapefile 仅保留兼容读取层，不再作为官方推荐入口。

## 官方入口

### official end-to-end
```bash
python -m rcsd_topo_poc t01-run-skill-v1 \
  --road-path <roads.geojson> \
  --node-path <nodes.geojson> \
  --out-root <out_root>
```

### 分步 / 调试入口
- `python -m rcsd_topo_poc t01-step1-pair-poc`
- `python -m rcsd_topo_poc t01-step2-segment-poc`
- `python -m rcsd_topo_poc t01-s2-refresh-node-road`
- `python -m rcsd_topo_poc t01-step4-residual-graph`
- `python -m rcsd_topo_poc t01-step5-staged-residual-graph`
- `python -m rcsd_topo_poc t01-step6-segment-aggregation-poc`

## debug 行为
- `debug=false`
  - 仅保留最终必要结果
  - official runner 仍跑到 Step6
  - 避免写出过多大体量中间层
- `debug=true`
  - 输出 Step1-Step6 的中间审计层与调试图层
  - 保留更丰富的 Step2 / Step5 / Step6 审计文件

## 正式业务字段
- node 侧正式字段：
  - `grade_2`
  - `kind_2`
  - `closed_con`
  - `working_mainnodeid`
- `working_mainnodeid` 作为内部 working 语义字段继续维护并优先供 Step1-Step6 使用，但不在公开 `nodes.geojson / inner_nodes.geojson` 中显式输出。
- roundabout preprocessing 是当前唯一允许同步修正公开 `mainnodeid` 的场景。
- road 侧正式输出字段：
  - `segmentid`
  - `sgrade`

## Step2 同阶段合法 pair 冲突仲裁
- Step2 仍先做单 pair 合法性验证，但 final `validated_pairs / segment_body` 不再由 pair 固定顺序直接决定。
- 当前新增 `same-stage pair arbitration`：
  - 识别合法 pair 的 `conflict components`
  - 在 component 内比较 contested corridor 的归属质量
  - 选出 winners 后再固化 final `segment_body` 与 `step3_residual`
- 当前优先关注：
  - contested trunk/corridor 覆盖
  - 端点边界是否自然
  - internal endpoint penalty
  - body connectivity support
  - semantic conflict penalty
  - strong anchor ownership
- `XXXS7` 是本轮定点样例，用于验证 `500588029` 的 corridor 归属不再由固定顺序贪心主导。

## official end-to-end 最终输出
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
- `validated_pairs_final.csv`
- `pair_conflict_table.csv`
- `pair_conflict_components.json`
- `pair_arbitration_table.csv`
- `corridor_conflict_roads.geojson`
- `skill_v1_manifest.json`
- `skill_v1_summary.json`

## 当前 accepted 约束
- 双向构段前置过滤：
  - node: `closed_con in {2,3}`
  - road: `road_kind != 1`
- 右转专用道约束：
  - `formway bit7` 的右转专用道不参与 Segment 构建
  - Step1 图搜索、Step4 residual graph、Step5 staged residual graph 均应先排除右转专用道
  - 若某节点在去除右转专用道后不再构成真实路口，则该节点不得作为语义路口、boundary 或 through 结构参与构段
  - 因此 `kind_2 = 1` 不得因仅挂接右转专用道而被保留为构段路口
- 统一 50m gates：
  - `MAX_DUAL_CARRIAGEWAY_SEPARATION_M = 50.0`
  - `MAX_SIDE_ACCESS_DISTANCE_M = 50.0`
- Step2 单侧旁路保留口径：
  - 只允许保留“单向且与主路平行”的单侧旁路系统
  - 若 non-trunk component 自身包含双向 side road，则不能作为合法单侧旁路保留，统一转 `step3_residual`
- Step2 / Step4 / Step5 全阶段 T 型路口前置门禁：
  - 若 trunk candidate 属于 `bidirectional_minimal_loop`
  - 且其内部路径主要由弱 connector node 串接，并借内部 T-support / support anchor 闭合
  - 则在 `single-pair validation` 直接按 `t_junction_vertical_tracking_blocked` 拒绝
  - 只要该 T 型路口不是 segment 起点 / 终点，该规则都必须生效
  - 该类 pair 不再进入 same-stage pair arbitration，也不得在后续 Step4 / Step5 重新构出
- Step5A / Step5B 保持 strict
- Step5C 使用 adaptive barrier fallback

## 当前活动 baseline
- `modules/t01_data_preprocess/baselines/t01_skill_active_five_sample_suite/XXXS/`
- `modules/t01_data_preprocess/baselines/t01_skill_active_five_sample_suite/XXXS2/`
- `modules/t01_data_preprocess/baselines/t01_skill_active_five_sample_suite/XXXS3/`
- `modules/t01_data_preprocess/baselines/t01_skill_active_five_sample_suite/XXXS4/`
- `modules/t01_data_preprocess/baselines/t01_skill_active_five_sample_suite/XXXS5/`

## 文档索引
- 规格：[spec.md](/mnt/e/Work/RCSD_Topo_Poc/specs/t01-data-preprocess/spec.md)
- 契约：[INTERFACE_CONTRACT.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/INTERFACE_CONTRACT.md)
- 架构概览：[overview.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/architecture/overview.md)
