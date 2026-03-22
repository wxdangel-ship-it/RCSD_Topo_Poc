# T01 数据预处理模块

## 当前状态
- 当前版本：`T01 Skill v1.0.0`
- 官方完整流程：`working bootstrap -> roundabout preprocessing -> Step1 -> Step2 -> Step3(refresh) -> Step4 -> Step5A -> Step5B -> Step5C -> Step6`
- Step6 已正式纳入 official end-to-end，不再是附加 POC

## 官方输入
- 官方推荐输入统一为 GeoJSON：
  - `nodes.geojson`
  - `roads.geojson`
- Shapefile 仅保留兼容层，不再作为官方示例命令。

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
  - 只保留最终必要结果
  - official runner 仍会跑到 Step6
  - 避免写出过多大体量中间层
- `debug=true`
  - 输出 Step1-Step6 的中间审计层与调试图层
  - 保留 Step5 的 alias refreshed 输出和更丰富的审计文件

## 正式业务字段
- node 侧正式字段：
  - `grade_2`
  - `kind_2`
  - `working_mainnodeid`
- `working_mainnodeid` 作为内部 working 语义字段继续维护并优先供 Step1-Step6 使用，但不在公开 `nodes.geojson` / `inner_nodes.geojson` 中显式输出
- 环岛预处理例外：
  - 聚合成环岛的一组 node 会同步修正 `mainnodeid / working_mainnodeid`
  - 环岛 `mainnode` 记为 `grade_2 = 1, kind_2 = 64`
  - 环岛 member node 记为 `grade_2 = 0, kind_2 = 0`
- road 侧正式输出字段：
  - `segmentid`
  - `sgrade`
- `s_grade`、`segment_id`、`Segment_id` 仅在读取兼容层中被识别。

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
- `skill_v1_manifest.json`
- `skill_v1_summary.json`

## Step6 定位
- Step6 把 road-level `segmentid` 结果聚合为 segment-level 图层。
- Step6 输出：
  - `segment.geojson`
  - `inner_nodes.geojson`
  - `segment_error.geojson`
  - `segment_error_s_grade_conflict.geojson`
  - `segment_error_grade_kind_conflict.geojson`
  - `segment_summary.json`
  - `segment_build_table.csv`
  - `inner_nodes_summary.json`
- Step6 standalone 从公开 `nodes.geojson` 读取时，若未显式带出 `working_mainnodeid`，则回退使用修正后的 `mainnodeid`。
- Step6 在 official runner 中复用 Step5 的内存态结果，不重新独立跑一套 `nodes / roads` 读取、`mainnode` 分组和邻接构建。

## 当前 accepted 约束
- 双向构段前置过滤：
  - node：`closed_con in {2,3}`
  - road：`road_kind != 1`
- 统一 50m gates：
  - `MAX_DUAL_CARRIAGEWAY_SEPARATION_M = 50.0`
  - `MAX_SIDE_ACCESS_DISTANCE_M = 50.0`
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
