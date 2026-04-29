# t04_divmerge_virtual_polygon

> 本文件是 `t04_divmerge_virtual_polygon` 的操作者入口说明。长期源事实以 `INTERFACE_CONTRACT.md` 与 `architecture/*` 为准；本文件只保留定位、入口、输入输出概览与阅读顺序。

## 1. 模块定位

T04 面向分歧、合流、连续分歧 / 合流以及复杂连续链路口，基于 SWSD 候选、局部道路面、DivStripZone、RCSDRoad / RCSDNode 等输入，生成受道路面约束的虚拟锚定面，并发布可审计的 batch / full-input 成果。

当前正式范围是 `Step1-7`：

1. `Step1 = candidate admission`
2. `Step2 = high-recall local context`
3. `Step3 = topology skeleton`
4. `Step4 = fact event interpretation`
5. `Step5 = geometric support domain`
6. `Step6 = polygon assembly`
7. `Step7 = final acceptance and publishing`

T04 的正式几何主产物仍是 `divmerge_virtual_anchor_surface*`；`nodes.gpkg` 与 `nodes_anchor_update_audit.csv/json` 是 downstream 状态回写产物，不替代 surface 几何真值。

## 2. 正式范围与非目标

当前支持：

- `diverge / merge / continuous complex 128` 候选。
- 单 case `case-package` 执行。
- internal full-input 执行：一次性加载 full-layer source，发现候选，按 case 直跑 Step1-7，并在 batch closeout 生成发布层、summary、audit、consistency report 与 downstream nodes 输出。

当前非目标：

- 不新增 repo 官方 CLI。
- 不推进 T03/T04 成果统一命名；T04 surface 主产物不改名。
- 不把 Step4 的 `STEP4_REVIEW` 重新解释为 Step7 最终第三态。
- 不把 `857993 = rejected` 当作待修成 `accepted` 的缺陷。

## 3. 当前入口状态

当前没有 repo 官方 CLI。稳定执行面是模块内 Python runner：

- `run_t04_step14_batch(...)`
- `run_t04_step14_case(...)`
- `run_t04_internal_full_input(...)`

internal full-input repo 级脚本入口：

- `scripts/t04_run_internal_full_input_8workers.sh`
- `scripts/t04_watch_internal_full_input.sh`
- `scripts/t04_run_internal_full_input_innernet_flat_review.sh`

这些脚本是已登记的包装入口，不是新的 CLI 子命令；执行语义仍由 T04 私有 orchestration 管理。

## 4. 输入与输出概览

默认本地 case 根：`/mnt/e/TestData/POC_Data/T02/Anchor_2`

典型 case-package 输入：

- `manifest.json`
- `size_report.json`
- `drivezone.gpkg`
- `divstripzone.gpkg`
- `nodes.gpkg`
- `roads.gpkg`
- `rcsdroad.gpkg`
- `rcsdnode.gpkg`

典型 full-input 输入：

- full-layer `nodes / roads / DriveZone / DivStripZone / RCSDRoad / RCSDNode`

典型 batch / full-input 根输出：

- `divmerge_virtual_anchor_surface.gpkg`
- `divmerge_virtual_anchor_surface_rejected.*`
- `divmerge_virtual_anchor_surface_summary.*`
- `divmerge_virtual_anchor_surface_audit.gpkg`
- `step7_rejected_index.*`
- `step7_consistency_report.json`
- `nodes.gpkg`
- `nodes_anchor_update_audit.csv`
- `nodes_anchor_update_audit.json`

典型 review 输出：

- `cases/<case_id>/final_review.png`
- `cases/<case_id>/event_units/<event_unit_id>/step4_review.png`
- `step4_review_flat/*.png`
- `step4_review_index.csv`
- `step4_review_summary.json`
- `visual_checks/final_by_state/{accepted,rejected}/*.png`
- `visual_checks/final_flat/*.png`

## 5. 当前冻结基线

当前 Anchor_2 full baseline 为：

- `row_count = 23`
- `accepted = 20`
- `rejected = 3`
- `857993 = rejected`，且这是人工验收确认后的正确业务结论
- `699870 = accepted`，并作为 RCSD-anchored reverse 关键回归样本

Step7 最终状态机只允许 `accepted / rejected`。downstream `nodes.gpkg` 写回语义为 `accepted -> yes`，`rejected / runtime_failed / formal result missing -> fail4`。

## 6. 文档阅读顺序

1. `architecture/01-introduction-and-goals.md`
2. `architecture/03-context-and-scope.md`
3. `architecture/04-solution-strategy.md`
4. `architecture/05-building-block-view.md`
5. `INTERFACE_CONTRACT.md`
6. `architecture/10-quality-requirements.md`
7. `architecture/11-risks-and-technical-debt.md`
8. `architecture/12-glossary.md`
