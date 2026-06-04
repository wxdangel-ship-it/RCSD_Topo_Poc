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

- 不推进 T03/T04 成果统一命名；T04 surface 主产物不改名。
- 不把 Step4 的 `STEP4_REVIEW` 重新解释为 Step7 最终第三态。
- 不把 `857993 = rejected` 当作待修成 `accepted` 的缺陷。

## 3. 当前入口状态

稳定执行面是模块内 Python runner：

- `run_t04_step14_batch(...)`
- `run_t04_step14_case(...)`
- `run_t04_internal_full_input(...)`

internal full-input repo 级脚本入口：

- `scripts/t04_run_internal_full_input_8workers.sh`
- `scripts/t04_watch_internal_full_input.sh`
- `scripts/t04_run_internal_full_input_innernet_flat_review.sh`

这些脚本是已登记的包装入口，不是新的 CLI 子命令；执行语义仍由 T04 私有 orchestration 管理。

单文件文本证据包提供 repo CLI，底层复用 T03 模块中的 T03/T04 共用打包模块，输入按 SWSD 语义路口 `mainnodeid`：

```bash
.venv/bin/python -m rcsd_topo_poc t04-export-text-bundle \
  --nodes-path nodes.gpkg \
  --roads-path roads.gpkg \
  --drivezone-path DriveZone.gpkg \
  --divstripzone-path DivStripZone.gpkg \
  --rcsdroad-path RCSDRoad.gpkg \
  --rcsdnode-path RCSDNode.gpkg \
  --mainnodeid 699870 760598 \
  --out-txt outputs/_work/t04_text_bundle/cases.txt

.venv/bin/python -m rcsd_topo_poc t04-decode-text-bundle \
  --bundle-txt outputs/_work/t04_text_bundle/cases.txt \
  --out-dir outputs/_work/t04_text_bundle/decoded
```

超过默认 `250KB` 时会自动生成 `*.part_XXXX_of_YYYY.txt` 分片；解包传入第 1 个 part 即可恢复完整 case-package。

内网脚本支持位置参数或 `--mainnodeid` 传多个语义路口 ID，并支持用命令参数覆盖所有输入文件路径：

```bash
scripts/t04_export_text_bundle_internal_multi_mainnodeids.sh \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg \
  --roads-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg \
  --drivezone-path /mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg \
  --divstripzone-path /mnt/d/TestData/POC_Data/patch_all/DivStripZone.gpkg \
  --rcsdroad-path /mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg \
  --rcsdnode-path /mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg \
  --out-txt /mnt/d/TestData/POC_Data/T04/t04_bundle.txt \
  --mainnodeid 706389 707476
```

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

Anchor_2 official 39-case baseline 是当前唯一正式冻结基线：

- 输入集：`/mnt/e/TestData/POC_Data/T02/Anchor_2`
- Windows 等价路径：`E:\TestData\POC_Data\T02\Anchor_2`
- `row_count = 39`
- `accepted = 35`
- `rejected = 4`
- rejected set：`607602562`、`760598`、`760936`、`857993`
- `699870 = accepted`，并作为 RCSD-anchored reverse 关键回归样本

历史 23/30 case 只是 official 39-case 内的子集：

- `legacy_23_20260426` 投影结果：`accepted = 20 / rejected = 3`
- `legacy_30_20260501` 投影结果：`accepted = 26 / rejected = 4`
- 子集定义与 official 39-case 结果统一维护在 `tests/modules/t04_divmerge_virtual_polygon/data/anchor2_official_39case_baseline_20260504.json`

PNG raw fingerprint 不再作为当前 hard gate。当前视觉 QA 锁定 `final_review.png` 存在性、render audit 与人工目视确认的 run root；历史 23-case PNG hash 只作为旧审计材料保留。

Step7 最终状态机只允许 `accepted / rejected`。downstream `nodes.gpkg` 写回语义为 `accepted -> yes`，Step8 fallback relation 成功时写 `fail4_fallback`，其余 `rejected / runtime_failed / formal result missing` 写 `fail4`。

## 6. 文档阅读顺序

1. `architecture/01-introduction-and-goals.md`
2. `architecture/03-context-and-scope.md`
3. `architecture/04-solution-strategy.md`
4. `architecture/05-building-block-view.md`
5. `INTERFACE_CONTRACT.md`
6. `architecture/10-quality-requirements.md`
7. `architecture/11-risks-and-technical-debt.md`
8. `architecture/12-glossary.md`
