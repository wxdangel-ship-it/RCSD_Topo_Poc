# T01 Architecture Overview

## 文档定位
- 本目录承载 `t01_data_preprocess` 的模块级源事实。
- 当前正式 source of truth 组合为：
  - [06-accepted-baseline.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/architecture/06-accepted-baseline.md)
  - [INTERFACE_CONTRACT.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/INTERFACE_CONTRACT.md)
  - 本目录下其余架构分解文档
- `specs/t01-data-preprocess/` 仅承载当前治理轮次的 spec-kit 文档，不再作为 accepted baseline 主承载。

## 当前 accepted architecture
- `raw vector input`
- `working bootstrap`
- `roundabout preprocessing`
- `bootstrap node retyping`
- `Step1`
- `Step2`
- `Step3 refresh`
- `Step4`
- `Step5A`
- `Step5B`
- `Step5C`
- `Step6`

## 关键原则
- 官方矢量输入统一为 `nodes.gpkg / roads.gpkg`。
- 同名输入并存时统一优先 `GeoPackage(.gpkg)`；历史 `.gpkt` 仅兼容读取。
- working node 业务判断统一使用 `grade_2 / kind_2`。
- working road 正式输出统一使用 `segmentid / sgrade`。
- 除 `slice_builder` 外，官方矢量输出统一为 `.gpkg`。
- 环岛预处理位于 Step1 前，并将环岛 `mainnode` 固化为：
  - `grade_2 = 1`
  - `kind_2 = 64`
- `bootstrap node retyping` 位于环岛预处理之后、Step1 之前。
- `bootstrap node retyping` 只允许修正 `grade_2 / kind_2`，不改原始 `grade / kind`。
- `bootstrap node retyping` 当前只支持极窄的严格 T 型纠错：
  - `grade_2 = 1`
  - `kind_2 = 4`
  - 且命中 `strict_t_to_grade2_kind2048`
- `formway = 128` 的右转专用道不参与 Step1-Step5 构段。
- `Step2 / Step4 / Step5*` 共享：
  - `50m` 双线垂距 gate
  - `50m` 侧向并入 gate
  - `kind_2 = 2048` 的 T 型路口竖向阻断规则
- Step3 / Step4 / Step5* 的节点刷新，不再使用泛化 `t_like => 2048` 口径，而是基于邻接 family 结构做：
  - `1/4 -> 2/2048`
  - 或 `1/4 -> 2/4`

## 文档分工
- [01-introduction-and-goals.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/architecture/01-introduction-and-goals.md)
  - 模块定位与文档边界
- [02-constraints.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/architecture/02-constraints.md)
  - 全局业务约束与治理约束
- [03-context-and-scope.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/architecture/03-context-and-scope.md)
  - 当前 in-scope / out-of-scope
- [04-solution-strategy.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/architecture/04-solution-strategy.md)
  - 阶段性解决策略与阶段间语义传播
- [05-building-block-view.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/architecture/05-building-block-view.md)
  - 代码组件与职责边界
- [06-accepted-baseline.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/architecture/06-accepted-baseline.md)
  - 当前 accepted baseline 正文
- [10-quality-requirements.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/architecture/10-quality-requirements.md)
  - 质量、审计与回归要求
- [11-risks-and-technical-debt.md](/mnt/e/Work/RCSD_Topo_Poc/modules/t01_data_preprocess/architecture/11-risks-and-technical-debt.md)
  - 当前风险、技术债与后续整改入口

## 临时样例基线
- `XXXS*` 临时最终 Segment 基线仅用于迭代中的非回退闸门。
- 它不覆盖 accepted baseline。
- 记录位置：
  - `modules/t01_data_preprocess/baselines/t01_skill_temp_segment_review_suite/TEMP_SEGMENT_BASELINE_MANIFEST.json`
  - `modules/t01_data_preprocess/baselines/t01_skill_temp_segment_review_suite/TEMP_SEGMENT_REVIEW.md`
