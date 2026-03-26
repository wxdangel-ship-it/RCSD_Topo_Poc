# T01 数据预处理模块

## 模块定位
- 面向非封闭式双向道路场景的双向 Segment 构建模块。
- 正式流程：
  - `working bootstrap -> roundabout preprocessing -> bootstrap node retyping -> Step1 -> Step2 -> Step3 -> Step4 -> Step5A -> Step5B -> Step5C -> Step6`
- Step6 已正式纳入 official end-to-end，不再是额外 POC。

## 官方输入
- 官方矢量输入文件名：
  - `nodes.gpkg`
  - `roads.gpkg`
- 兼容读取：
  - 同名 `GeoPackage(.gpkg)` 优先
  - 历史 `.gpkt` 仅兼容读取
  - `GeoJSON(.geojson/.json)` 与 `Shapefile(.shp)` 继续兼容

## 当前 accepted 约束摘要
- node 输入：
  - `closed_con in {2,3}`
- road 输入：
  - `road_kind != 1`
  - `formway != 128`
- 后续业务判断统一使用：
  - `grade_2`
  - `kind_2`
- 原始 `grade / kind` 仅保留为输入信息，不再作为后续业务判断依据。

## 关键业务口径
- 环岛预处理在模块开始阶段完成，环岛 `mainnode` 统一写成：
  - `grade_2 = 1`
  - `kind_2 = 64`
- `bootstrap node retyping` 位于环岛预处理之后、Step1 之前：
  - 只修正 `grade_2 / kind_2`
  - 不改原始 `grade / kind`
  - 当前仅支持极窄的 strict-T 纠错：`1/4 -> 2/2048`
- Step3 / Step4 / Step5* 的节点刷新已改为 family-based retyping：
  - `1/4 -> 2/2048`
  - 或 `1/4 -> 2/4`
  - 不再使用旧的泛化 `t_like => 2048` 叙述
- 全局共享：
  - `50m` 双线路段最小闭环垂距门控
  - `50m` 侧向并入距离门控
- T 型路口竖向阻断规则：
  - 仅对应 `kind_2 = 2048`
  - 只要不是当前 segment 的起点 / 终点，在 `Step2 / Step4 / Step5*` 中都禁止内部竖向追溯
- 右转专用道：
  - `formway bit7 / 128` 的 road 不参与 Segment 构建
  - 去掉右转专用道后不成真实路口的节点，不得作为构段路口

## 官方入口

### official end-to-end
```bash
python -m rcsd_topo_poc t01-run-skill-v1 \
  --road-path <roads.gpkg> \
  --node-path <nodes.gpkg> \
  --out-root <out_root>
```

### 分步 / 调试入口
- `python -m rcsd_topo_poc t01-step1-pair-poc`
- `python -m rcsd_topo_poc t01-step2-segment-poc`
- `python -m rcsd_topo_poc t01-s2-refresh-node-road`
- `python -m rcsd_topo_poc t01-step4-residual-graph`
- `python -m rcsd_topo_poc t01-step5-staged-residual-graph`
- `python -m rcsd_topo_poc t01-step6-segment-aggregation-poc`

## 正式输出
- `nodes.gpkg`
- `roads.gpkg`
- `segment.gpkg`
- `inner_nodes.gpkg`
- `segment_error.gpkg`
- `segment_error_s_grade_conflict.gpkg`
- `segment_error_grade_kind_conflict.gpkg`
- `validated_pairs_skill_v1.csv`
- `segment_body_membership_skill_v1.csv`
- `trunk_membership_skill_v1.csv`
- `skill_v1_manifest.json`
- `skill_v1_summary.json`

说明：
- `slice_builder` 是当前唯一默认双写 `GeoJSON + GPKG` 的入口：
  - `nodes.geojson` + `nodes.gpkg`
  - `roads.geojson` + `roads.gpkg`
- 其余官方阶段矢量输出默认统一为 `.gpkg`。

## 文档索引
- 架构总览：`/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/architecture/overview.md`
- accepted baseline：`/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/architecture/06-accepted-baseline.md`
- 契约：`/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/INTERFACE_CONTRACT.md`
- spec-kit 计划：`/mnt/e/Work/RCSD_Topo_Poc/specs/t01-data-preprocess/plan.md`
- spec-kit 任务：`/mnt/e/Work/RCSD_Topo_Poc/specs/t01-data-preprocess/tasks.md`

## 临时样例基线
- `XXXS*` 的临时最终 Segment 基线仅用于迭代过程中的非回退检查。
- 不覆盖 accepted baseline。
- 记录位置：
  - `modules/t01_data_preprocess/baselines/t01_skill_temp_segment_review_suite/TEMP_SEGMENT_BASELINE_MANIFEST.json`
  - `modules/t01_data_preprocess/baselines/t01_skill_temp_segment_review_suite/TEMP_SEGMENT_REVIEW.md`
