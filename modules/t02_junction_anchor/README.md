# t02_junction_anchor

> 本文件是 `t02_junction_anchor` 的操作者总览与运行入口说明。当前业务需求对齐与 accepted baseline 以 `architecture/06-accepted-baseline.md` 为准，稳定输入/输出/入口契约以 `INTERFACE_CONTRACT.md` 为准；如本文件与长期源事实表述不一致，以后者为准。

## 1. 模块定位

- T02 是当前已登记的正式业务模块。
- 当前正式实现范围包括：
  - stage1 `DriveZone / has_evd gate`
  - stage2 `anchor recognition / anchor existence`
  - stage3 `virtual intersection anchoring`
  - stage4 `diverge / merge virtual polygon`
  - 连续分歧 / 合流复杂路口聚合离线工具
- 模块长期目标是为双向 Segment 相关路口锚定提供可审计、可复现的下游基础。
- `t02-virtual-intersection-poc` 是当前 stage3 baseline 官方入口。
- `t02-stage4-divmerge-virtual-polygon` 是当前 stage4 独立入口，只输出虚拟路口面及关联审计，不回写 `nodes.is_anchor`。
- 单 / 多 `mainnodeid` 文本证据包当前作为 stage3 复核与外部复现支撑工具保留。
- 当前代码已实现最小闭环，但尚未进入最终唯一锚定决策、概率阶段与正式产线级全量批处理。

### Stage4 摘要

- 当前定位：面向分歧 / 合流场景的独立补充阶段；当前不写回 `nodes.is_anchor`，不并入统一锚定结果，也不承担最终唯一锚定闭环。
- 当前处理对象：`has_evd = yes`、`is_anchor = no` 且需要按真实分歧 / 合流事件解释的事实路口候选；包括简单 div/merge 候选和连续分歧 / 合流聚合后的 complex 128 主节点，不等于“所有 complex 128”。
- 当前非目标：不做候选生成 / 打分，不做概率 / 置信度，不做误伤捞回，不做环岛新规则。
- 审计与目视复核：复用 Stage3 的机器审计 + 人工目视双线模板与三态 PNG 样式，但不继承 Stage3 业务语义。
- 最终成果输出：Stage4 产出 `stage4_virtual_polygon.gpkg` / `stage4_virtual_polygons.gpkg` 及关联审计；polygon 图层至少承载 `mainnodeid`、`kind` 和 Stage4 审计字段，支持脱离 JSON 的基本独立复核。

## 2. 官方运行入口

```bash
python -m rcsd_topo_poc t02-stage1-drivezone-gate --help
```

```bash
python -m rcsd_topo_poc t02-stage2-anchor-recognition --help
```

```bash
python -m rcsd_topo_poc t02-virtual-intersection-poc --help
```

```bash
python -m rcsd_topo_poc t02-export-text-bundle --help
```

```bash
python -m rcsd_topo_poc t02-fix-node-error-2 --help
```

```bash
python -m rcsd_topo_poc t02-decode-text-bundle --help
```

```bash
python -m rcsd_topo_poc t02-stage4-divmerge-virtual-polygon --help
```

```bash
python -m rcsd_topo_poc t02-aggregate-continuous-divmerge --help
```

- `t02-virtual-intersection-poc` 是当前 stage3 baseline 官方入口
- 默认 `case-package` 模式保持既有单 `mainnodeid` baseline 回归能力
- 显式 `--input-mode full-input` 时，统一承接：
  - 完整数据 + 指定 `mainnodeid`
  - 完整数据 + 自动识别“有资料但未锚定”的路口
- 它不重算 stage1 `has_evd` 或 stage2 `is_anchor`，而是直接消费其结果字段
- `t02-fix-node-error-2` 是独立离线修复工具，只消费 `node_error_2 / nodes / roads / RCSDIntersection` 并输出 `nodes_fix.gpkg / roads_fix.gpkg / fix_report.json`；它不属于 stage 主流程
- `t02-export-text-bundle` / `t02-decode-text-bundle` 用于单 / 多 `mainnodeid` 文本证据包导出与解包，服务于 stage3 复核与外部复现
- `t02-stage4-divmerge-virtual-polygon` 用于单 case 的 div/merge 虚拟路口面 baseline，输入为 `nodes / roads / DriveZone / DivStripZone / RCSDRoad / RCSDNode / mainnodeid`；当前处理对象包括简单 div/merge 候选，以及连续分歧 / 合流聚合后的 complex 128 主节点
- `t02-aggregate-continuous-divmerge` 是独立离线聚合工具，按 T04 continuous chain 语义识别连续分歧/合流组，改写 `nodes / roads` 并输出 `nodes_fix.gpkg / roads_fix.gpkg / continuous_divmerge_report.json`
- 该工具会同步输出：
  - 新生成复杂路口数量 `complex_junction_count`
  - 新生成复杂路口 `mainnodeid` 列表 `complex_mainnodeids`
  - CLI 结束时也会直接打印这两个摘要
- T02 当前输入兼容 `GeoPackage(.gpkg)`、`GeoJSON` 与 `Shapefile`；历史 `.gpkt` 后缀仅做兼容读取；若同名 `.gpkg` 与 `.geojson` 同时存在，默认优先读取 `GeoPackage`
- T02 当前矢量输出统一写为 `GeoPackage(.gpkg)`；文本证据包仍输出单个 txt，但解包后的矢量文件也统一为 `.gpkg`
- `case-package` 是 stage3 唯一正式验收基线入口，不允许回退
- 当前唯一正式验收基线冻结为 `E:\TestData\POC_Data\T02\Anchor`（WSL：`/mnt/e/TestData/POC_Data/T02/Anchor`）下的 `61` 个 case
- `full-input` 当前仅作为 fixture / dev-only / regression 入口；共享大图层直连运行必须先满足正确 layer / CRS / 预裁剪与 preflight 约束
- `test_virtual_intersection_full_input_poc.py` 当前只承担 regression 角色，不再表述为 Stage3 正式交付基线
## 3. 常见运行方式

```bash
python -m rcsd_topo_poc t02-stage1-drivezone-gate \
  --segment-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.gpkg \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/nodes.gpkg \
  --drivezone-path /mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_stage1_drivezone_gate \
  --run-id t02_stage1_run
```

```bash
python -m rcsd_topo_poc t02-stage2-anchor-recognition \
  --segment-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.gpkg \
  --nodes-path /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_stage1_drivezone_gate/t02_stage1_run/nodes.gpkg \
  --intersection-path /mnt/d/TestData/POC_Data/patch_all/RCSDIntersection.gpkg \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_stage2_anchor_recognition \
  --run-id t02_stage2_run
```

stage3 示例：

```bash
python -m rcsd_topo_poc t02-virtual-intersection-poc \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/stage2/nodes.gpkg \
  --roads-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/roads.gpkg \
  --drivezone-path /mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg \
  --rcsdroad-path /mnt/d/TestData/POC_Data/patch_all/RCSDRoad.gpkg \
  --rcsdnode-path /mnt/d/TestData/POC_Data/patch_all/RCSDNode.gpkg \
  --mainnodeid 100 \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_virtual_intersection_poc \
  --debug-render-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_virtual_intersection_poc_debug/_rendered_maps \
  --run-id t02_virtual_intersection_demo
```

stage4 示例：

```bash
python -m rcsd_topo_poc t02-stage4-divmerge-virtual-polygon \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg \
  --roads-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg \
  --drivezone-path /mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg \
  --divstripzone-path /mnt/d/TestData/POC_Data/patch_all/DivStripZone.gpkg \
  --rcsdroad-path /mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg \
  --rcsdnode-path /mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg \
  --mainnodeid 100 \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_stage4_divmerge_virtual_polygon \
  --run-id t02_stage4_divmerge_demo \
  --debug-render-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_stage4_divmerge_virtual_polygon/t02_stage4_divmerge_demo/visual_checks \
  --debug
```

连续分歧 / 合流聚合工具示例：

```bash
python -m rcsd_topo_poc t02-aggregate-continuous-divmerge \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg \
  --roads-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg \
  --nodes-fix-path /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_continuous_divmerge/nodes_fix.gpkg \
  --roads-fix-path /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_continuous_divmerge/roads_fix.gpkg \
  --report-path /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_continuous_divmerge/continuous_divmerge_report.json
```

内网 Stage4 全量运行脚本：

```bash
bash scripts/t02_run_stage4_internal_full_input_8workers.sh
```

内网 Stage4 监控脚本：

```bash
bash scripts/t02_watch_stage4_internal_full_input.sh
```

说明：

- 自动发现只处理符合 Stage4 baseline 的代表 node：`has_evd = yes`、`is_anchor = no`，且属于需要按真实分歧 / 合流事件解释的事实路口候选；当前包含简单 div/merge 候选，以及连续分歧 / 合流聚合后的 complex 128 主节点。
- 默认内网路径冻结为：
  - `NODES_PATH=/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg`
  - `ROADS_PATH=/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg`
  - `DRIVEZONE_PATH=/mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg`
  - `DIVSTRIPZONE_PATH=/mnt/d/TestData/POC_Data/patch_all/DivStripZone.gpkg`
  - `RCSDROAD_PATH=/mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg`
  - `RCSDNODE_PATH=/mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg`
- 默认 `WORKERS=8`，按 case 并行调用单 case Stage4 入口。
- 每个 case 输出目录固定为：
  - `<OUT_ROOT>/<RUN_ID>/cases/<mainnodeid>/`
- batch 汇总固定输出到：
  - `<OUT_ROOT>/<RUN_ID>/batch_summary.json`
- 监控脚本默认盯住 `OUT_ROOT` 下最新批次；也可显式传：
  - `RUN_ID=t02_stage4_divmerge_full_input_internal_20260403_120000 bash scripts/t02_watch_stage4_internal_full_input.sh`
  - `RUN_ROOT=/mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_stage4_divmerge_full_input_internal/<RUN_ID> bash scripts/t02_watch_stage4_internal_full_input.sh`
- 监控脚本默认每 `10s` 刷新一次，并在检测到 `batch_summary.json` 后自动停止。
- 如只想打印一次当前状态，可传：
  - `ONCE=1 bash scripts/t02_watch_stage4_internal_full_input.sh`
- 若你内网 `nodes.gpkg` 不在默认位置，也可临时覆盖：
  - `NODES_PATH=/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg bash scripts/t02_run_stage4_internal_full_input_8workers.sh`
- 当前 Stage4 已正式消费 `DivStripZone`：
  - 在合法 `DriveZone` patch 内，它是局部分支裁决和虚拟面约束的一级参考
  - nearby 缺失或未提供输入时，会先降级到 `roads / RCSDRoad` 支撑面
  - 多组件歧义或覆盖不完整时，才进入 `review_required`

```bash
python -m rcsd_topo_poc t02-virtual-intersection-poc \
  --input-mode full-input \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/stage2/nodes.gpkg \
  --roads-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg \
  --drivezone-path /mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg \
  --rcsdroad-path /mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg \
  --rcsdnode-path /mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg \
  --max-cases 100 \
  --workers 8 \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_virtual_intersection_full_input \
  --run-id t02_virtual_intersection_full_input_demo \
  --debug
```

全量自动发现包装脚本：

```bash
NODES_PATH=/mnt/e/TestData/POC_Data/first_layer_road_net_v0/T02/stage2/nodes.gpkg \
ROADS_PATH=/mnt/e/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg \
DRIVEZONE_PATH=/mnt/e/TestData/POC_Data/patch_all/DriveZone.gpkg \
RCSDROAD_PATH=/mnt/e/TestData/POC_Data/RC4/RCSDRoad.gpkg \
RCSDNODE_PATH=/mnt/e/TestData/POC_Data/RC4/RCSDNode.gpkg \
WORKERS=8 \
bash scripts/t02_run_stage3_full_input_8workers.sh
```

说明：

- 全量 `full-input` 自动发现只处理符合 Stage3 baseline 的代表 node：`has_evd = yes`、`is_anchor = no`、`kind_2 in {4, 2048}`。
- `NODES_PATH` 应指向 stage2 已完成字段补齐的 `nodes.gpkg`，至少具备：`id / mainnodeid / has_evd / is_anchor / kind_2 / grade_2`。
- `ROADS_PATH / DRIVEZONE_PATH / RCSDROAD_PATH / RCSDNODE_PATH` 应为与该批次空间范围一致、CRS 可正确识别的全量输入。
- 包装脚本只是复用官方入口 `python -m rcsd_topo_poc t02-virtual-intersection-poc --input-mode full-input`，不会引入新的业务语义。

内网 8 线程全量运行脚本：

```bash
bash scripts/t02_run_stage3_internal_full_input_8workers.sh
```

说明：

- 默认内网路径冻结为：
  - `NODES_PATH=/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg`
  - `ROADS_PATH=/mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg`
  - `DRIVEZONE_PATH=/mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg`
  - `DIVSTRIPZONE_PATH=/mnt/d/TestData/POC_Data/patch_all/DivStripZone.gpkg`
  - `RCSDROAD_PATH=/mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg`
  - `RCSDNODE_PATH=/mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg`
- Stage4 当前正式读取 `DivStripZone` 的局部 patch；它是合法 `DriveZone` patch 内的一级局部参考，用于分支裁决和虚拟面约束，不直接作为输出 polygon。
- 若局部 patch 中缺少 nearby `DivStripZone` 或未提供该输入，默认先降级到 `roads / RCSDRoad` 支撑面，并在 `stage4_status.json / stage4_audit.json` 中写出 `divstrip_present / divstrip_nearby / divstrip_component_count / divstrip_component_selected / selection_mode / evidence_source`。
- `mainnodeid` 对应的主 `RCSDNode` 不再无条件当作精确 seed：
  - `kind_2=16` 允许位于分歧前主干 `<=20m`
  - `kind_2=8` 允许位于合流后主干 `<=20m`
  - 若超窗、方向错误或 off-trunk，会在 `stage4_status.json / stage4_audit.json` 中写出 `trunk_branch_id / rcsdnode_tolerance_rule / rcsdnode_tolerance_applied / rcsdnode_coverage_mode / rcsdnode_offset_m / rcsdnode_lateral_dist_m`，并进入 `review_required`
- 默认 `WORKERS=8`，默认开启 `--debug`。
- 所有目视检查 PNG 统一输出到：
  - `<OUT_ROOT>/<RUN_ID>/visual_checks/`
- 如需限量试跑，可额外传：
  - `MAX_CASES=100 bash scripts/t02_run_stage3_internal_full_input_8workers.sh`

```bash
python -m rcsd_topo_poc t02-fix-node-error-2 \
  --node-error2-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02_Fix/node_error_2.gpkg \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02_Fix/nodes.gpkg \
  --roads-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02_Fix/roads.gpkg \
  --intersection-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02_Fix/RCSDIntersection.gpkg \
  --nodes-fix-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02_Fix/nodes_fix.gpkg \
  --roads-fix-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02_Fix/roads_fix.gpkg \
  --report-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02_Fix/fix_report.json
```

```bash
python -m rcsd_topo_poc t02-export-text-bundle \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg \
  --roads-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg \
  --drivezone-path /mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg \
  --divstripzone-path /mnt/d/TestData/POC_Data/patch_all/DivStripZone.gpkg \
  --rcsdroad-path /mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg \
  --rcsdnode-path /mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg \
  --mainnodeid 765003 \
  --out-txt /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_text_bundle/case_765003.txt
```

```bash
python -m rcsd_topo_poc t02-export-text-bundle \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg \
  --roads-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg \
  --drivezone-path /mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg \
  --divstripzone-path /mnt/d/TestData/POC_Data/patch_all/DivStripZone.gpkg \
  --rcsdroad-path /mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg \
  --rcsdnode-path /mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg \
  --mainnodeid 765003 765154 922217 \
  --out-txt /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_text_bundle/cases_pack.txt
```

```bash
python -m rcsd_topo_poc t02-decode-text-bundle \
  --bundle-txt /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_text_bundle/case_765003.txt
```

```bash
cd /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_text_bundle
python -m rcsd_topo_poc t02-decode-text-bundle \
  --bundle-txt /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_text_bundle/cases_pack.txt
```

说明：

- `segment` 与 `nodes` 应来自同一轮 T01 成果。
- `DriveZone` 与 `nodes` 会在空间判定前统一到 `EPSG:3857`。
- `t02-export-text-bundle` 支持可选携带 `DivStripZone`；显式传入 `--divstripzone-path` 时，bundle 与解包目录中会额外包含 `divstripzone.gpkg`。
- `t02-decode-text-bundle` 解包后的 `nodes.gpkg / roads.gpkg / drivezone.gpkg / divstripzone.gpkg(若导出时提供) / rcsdroad.gpkg / rcsdnode.gpkg` 会恢复为绝对 `EPSG:3857` 坐标并写入 CRS，可直接作为 Stage3 / Stage4 case-package 输入，无需再额外传 CRS override。
- 官方默认工作输出根目录是 `outputs/_work/t02_stage1_drivezone_gate`。
- 显式传入 `--out-root` 时，其语义也是“工作输出根目录”；最终运行目录固定为 `<out_root>/<run_id>`。

## 4. 输出总览

补充：
- `--debug-render-root` 仅控制 debug 叠图 PNG 的批次归档位置，不改变正式运行目录 `<out_root>/<run_id>`。

- `nodes.gpkg`
  - 继承输入 `nodes` 字段并新增 `has_evd / is_anchor / anchor_reason`
  - 只有代表 node 写 `has_evd / is_anchor / anchor_reason`
  - `anchor_reason` 当前最小值域为 `roundabout / t / null`
  - 输出 geometry 统一为 `EPSG:3857`
- `segment.gpkg`
  - 继承输入 `segment` 字段并新增 `has_evd`
  - 输出 geometry 统一为 `EPSG:3857`
- `t02_stage1_summary.json`
  - 汇总总计数、按 `s_grade` 分桶的 summary、`all__d_sgrade`，以及按代表 node.`kind_2 / grade_2` 分级的 `summary_by_kind_grade`
- `t02_stage2_summary.json`
  - 汇总 stage2 的两组锚定 summary：
    - `anchor_summary_by_s_grade`
    - `anchor_summary_by_kind_grade`
  - “资料”只认 `has_evd = yes`
  - “锚定”只认 `is_anchor = yes`
- `t02_stage1_audit.csv`
- `t02_stage1_audit.json`
  - 保留 `junction_nodes_not_found`、`representative_node_missing`、`no_target_junctions`、`missing_required_field`、`invalid_crs_or_unprojectable` 等异常或失败原因
- `t02_stage1.log`
  - 运行日志与关键计数摘要
- `t02_stage1_progress.json`
  - 当前阶段、阶段消息和累计计数
- `t02_stage1_perf.json`
  - 总耗时、阶段耗时和总体计数
- `t02_stage1_perf_markers.jsonl`
  - 阶段级性能标记流
- `nodes_fix.gpkg`
  - `t02-fix-node-error-2` 的修复后完整 nodes 输出
- `roads_fix.gpkg`
  - `t02-fix-node-error-2` 的修复后完整 roads 输出
- `fix_report.json`
  - `t02-fix-node-error-2` 的独立审计输出，记录候选组、忽视的 `kind_2 = 1` 组、合并结果、删除 roads 与 skip reason
- `virtual_intersection_polygon.gpkg`
  - stage3 单 case 生成的虚拟路口面
  - 属于最终成果路口面图层，必须包含 `mainnodeid / kind`
  - `mainnodeid` 优先取代表 node 的 `nodes.mainnodeid`，为空或缺失时回退 `nodes.id`
  - `kind` 优先写代表 node 的 `nodes.kind`，为空或缺失时回退 `nodes.kind_2`
  - 输出 geometry 统一为 `EPSG:3857`
- `virtual_intersection_polygons.gpkg`
  - stage3 full-input 模式汇总生成的批次虚拟路口面图层
  - 属于 stage3 的最终全量路口面汇总图层
  - 每条成果必须包含 `mainnodeid / kind`
  - `mainnodeid` 优先取代表 node 的 `nodes.mainnodeid`，为空或缺失时回退 `nodes.id`
  - `kind` 优先写代表 node 的 `nodes.kind`，为空或缺失时回退 `nodes.kind_2`
  - 输出 geometry 统一为 `EPSG:3857`
- `stage4_virtual_polygon.gpkg`
  - stage4 单 case 生成的 div/merge 虚拟路口面
- `stage4_virtual_polygons.gpkg`
  - stage4 batch / 全量运行时的最终全量路口面汇总图层
  - 每条成果必须包含 `mainnodeid / kind`
  - `mainnodeid` 优先取代表 node 的 `nodes.mainnodeid`，为空或缺失时回退 `nodes.id`
  - `kind` 优先写代表 node 的 `nodes.kind`，为空或缺失时回退 `nodes.kind_2`
  - 输出 geometry 统一为 `EPSG:3857`
- `stage4_node_link.json`
  - stage4 与 `nodes.mainnodeid` 的关联结果
- `stage4_rcsdnode_link.json`
  - stage4 与 `RCSDNode` seed / 相关 node 的关联结果
- `stage4_audit.json`
  - stage4 审计结果
- `_rendered_maps/`
  - stage3 批次 render 目录
- 所有最终成果路口面图层统一遵循：
  - 必须带 `mainnodeid / kind`
  - `mainnodeid` 缺失时回退 `id`
  - geometry 统一写为 `EPSG:3857`
  - 只要存在 batch / full-input / 全量运行，就必须同步输出最终全量路口面汇总图层
- 成果审计当前统一采用双线模板：
  - 机器审计给根因层（`step3 / step4 / step5 / step6 / frozen-constraints conflict`）
  - 人工目视审计给快速分类（`V1 认可成功 / V2 业务正确但几何待修 / V3 漏包 required / V4 误包 foreign / V5 明确失败`）
- Stage4 当前复用同一套成果审计与目视复核模板
- `branch_evidence.json`
- `branch_evidence.gpkg`
  - 分支方向、证据等级、是否纳入虚拟面和 RC 方向组映射
- `associated_rcsdroad.gpkg`
- `associated_rcsdroad_audit.csv`
- `associated_rcsdroad_audit.json`
  - 已关联与未关联的 RCSDRoad 结果及审计
- `associated_rcsdnode.gpkg`
- `associated_rcsdnode_audit.csv`
- `associated_rcsdnode_audit.json`
  - 已关联与未关联的 RCSDNode 结果及审计
- `t02_virtual_intersection_poc_status.json`
- `t02_virtual_intersection_poc_audit.csv`
- `t02_virtual_intersection_poc_audit.json`
- `t02_virtual_intersection_poc.log`
- `t02_virtual_intersection_poc_progress.json`
- `t02_virtual_intersection_poc_perf.json`
- `t02_virtual_intersection_poc_perf_markers.jsonl`
  - 单 `mainnodeid` POC 的状态、风险、审计与性能输出
- 当前典型状态包括：
  - `stable`
  - `surface_only`
  - `weak_branch_support`
  - `ambiguous_rc_match`
  - `no_valid_rc_connection`
  - `node_component_conflict`
- `t02_single_case_bundle.txt`
  - 单 `mainnodeid` 文本证据包
- `t02_multi_case_bundle.txt`
  - 多 `mainnodeid` 文本证据包；解包后会在目标目录下生成多个 `<mainnodeid>/` case 目录
- 内含 `manifest.json`、`drivezone_mask.png`、`drivezone.gpkg`、`nodes.gpkg`、`roads.gpkg`、`rcsdroad.gpkg`、`rcsdnode.gpkg`、`size_report.json`
- `t02-decode-text-bundle` 未显式传入 `--out-dir` 时：
  - 单 case bundle 默认解包到与 bundle 同目录、且以 bundle 文件名为目录名的子目录；例如 `case_765003.txt -> case_765003/`
  - 多 case bundle 默认解包到当前工作目录，并展开为多个 `<mainnodeid>/` case 目录
  - 导出时强制检查最终文本体积 `<= 300KB`；超限时失败并输出体积分析报告

说明：

- stage1 正式候选边界已扩到“当前 `semantic_junction_set` 对应的目标 `junction_id` + `segment_referenced_junction_set`”。
- stage1 业务 summary 的 `summary_by_s_grade` 继续按 `0-0双 / 0-1双 / 0-2双` 的 segment 视图统计。
- stage1 在分桶之外补充 `all__d_sgrade`，表示所有 `s_grade` 非空的 `segment` 总汇总。
- stage1 同时补充 `summary_by_kind_grade`，固定输出 `kind2_4_64_grade2_1 / kind2_4_64_grade2_0_2_3 / kind2_2048 / kind2_8_16` 四个 bucket，并按 `stage1_candidate_junction_set` 唯一 `junction_id` 统计 `junction_count / junction_has_evd_count`。
- stage2 正式候选边界同样沿用“当前 `semantic_junction_set` 对应的目标 `junction_id` + `segment_referenced_junction_set`”，但 `summary_by_s_grade` 仍保持 segment 视图。
- `kind_2 in {8,16}` 在 stage2 仍参与 `RCSDIntersection` 锚定判定；若满足 Stage2 标准，同样可记 `is_anchor = yes`，仅 `is_anchor = no` 的 case 继续进入 Stage4。

## 5. 文档阅读顺序

1. `architecture/06-accepted-baseline.md`
2. `architecture/01-introduction-and-goals.md`
3. `architecture/02-constraints.md`
4. `architecture/04-solution-strategy.md`
5. `architecture/05-building-block-view.md`
6. `INTERFACE_CONTRACT.md`
7. `architecture/10-quality-requirements.md`

补充：

- `architecture/overview.md` 用于快速总览和索引，不替代标准 architecture 文档组。
- `architecture/06-accepted-baseline.md` 是当前 T02 模块需求对齐与 accepted baseline 主文档。
- `history/*` 保留阶段演进记录，不替代当前正式源事实。
- `specs/t02-junction-anchor/*` 与 `specs/t02-virtual-intersection-batch-poc/*` 是变更工件，不是长期模块真相主表面。

## 6. 当前实现范围

- 已实现：
  - stage1 输入读取与严格字段校验
  - 以“当前 `semantic_junction_set` 对应的目标 `junction_id` + `segment_referenced_junction_set`”构成 stage1 候选域
  - 步骤1中 `semantic_junction_set` 按“当前语义路口的 node 集合”定义，`mainnode` 仅作为代表，不等于整个语义路口
  - `pair_nodes + junc_nodes` 解析与单 `segment` 去重
  - `mainnodeid` 分组 / 单点兜底
  - 多节点语义组要求后续合法 polygon 一次性直接覆盖整组全部 node；不能完整覆盖时按问题 case 处理
  - `boundary roads / arms` 的 road 两端按可穿越 `degree=2` 过渡节点跟踪后的边界端点理解；仅当两个边界端点都不属于当前 `semantic_junction_set` 时，才算 `foreign boundary roads`
  - 判断误包其他语义路口不能只看 foreign node；纳入别的语义路口向外延伸到其他路口的 roads / arms 也视为错误
  - `connector road` 术语不再使用
  - 代表 node `has_evd` 写值
  - `segment.has_evd`
  - `summary`
  - `audit/log`
- 已冻结但当前以文档口径为准：
  - Stage3 步骤2「模板分类」中，`kind_2` 作为强输入使用
  - `kind_2 = 2048` 直接归入 `single_sided_t_mouth`
  - `kind_2 = 4` 先归入 `center_junction`
  - `kind_2 = 4` 的 `center_junction` 只表示后续可按中心型路口理解，不表示已经通过边界/入侵合法性检查；若后续发现 foreign boundary roads 或其他语义路口 roads / arms 入侵，则该 case 仍应视为问题 case
  - Stage3 步骤3「目标 corridor / 口门边界」中，后续 polygon 只能在当前模板允许占用的 `DriveZone` 内合法道路面中活动
  - 对与当前合法活动空间存在潜在冲突的 foreign elements，可先按 `1m` 负向缓冲构建硬排除区
  - `single_sided_t_mouth` 只能在目标单侧 lane corridor 内展开，不得跨到对向 lane 或对向主路 corridor
  - `center_junction` 可先按中心型路口铺满当前 case 的合法道路面，但不豁免 foreign boundary roads、其他语义路口 roads / arms 的入侵检查
  - `10m` 只作为附加臂方向的保守外扩上限，且不得压过“整组 node 一次性直接覆盖”与 foreign 硬边界
  - Stage3 步骤4「RCSD 关联语义」中，当前 case 的 `RC` 语义层级冻结为 A / B / C 三类：
    - A 类：`RCSD` 也构成语义路口，按整组 `RCSDNode` 处理
    - B 类：`RCSD` 不构成语义路口，但存在相关 `RCSDRoad`，只追加挂接区域语义
    - C 类：无相关 `RCSDRoad`
  - A 类单节点 `RC` 语义路口的“3 个方向”按“经过 `degree=2` 跟踪后的边界方向簇数”判定，不按字面 `RCSDRoad` 条数机械计数
  - 步骤4可以识别 `required RC`，但不能反向扩大步骤3已冻结的合法活动空间；若 `required RC` 落在步骤3合法空间之外，当前仅记为审计异常 / `stage3_rc_gap`
  - Stage3 步骤5「foreign SWSD / RCSD 排除规则」中，foreign 对象冻结为三类：
    - `foreign_semantic_nodes`
    - `foreign_roads_arms_corridors`
    - `foreign_rc_context`
  - `single_sided_t_mouth` 下，对向 lane / 对向主路 corridor / 非目标 mouth 的另一侧 corridor / 远端 `RC tail` 一律按 `foreign` 处理，不留容忍窗口
  - `center_junction` 下，其他语义路口外延 `roads / arms / lane corridor`、`foreign boundary roads`、以及只在 foreign 语义上下文里成立的 `RC`，只要进入当前 case 就视为错误
  - 步骤4中的 `excluded RC` 在步骤5中直接等价于 `foreign RC`
  - 单纯“边界接触”不算错；形成可活动、可占用、可依赖的“实际纳入”一律算错
-  - Stage3 步骤6「几何生成与后处理」中，步骤6是受约束的几何生成步骤，不是补面或洗白步骤
  - 步骤6的硬约束优先级固定为：先守步骤3合法活动空间，再守步骤5 `foreign` 硬排除，再满足步骤1 must-cover，再满足步骤4 `required RC` must-cover，最后才允许做几何优化
  - `single_sided_t_mouth` 的理想几何是围绕目标单侧 mouth 的单侧口门面；横向支路只贡献 mouth，纵向延伸只服务于闭合当前口门，不得跨对向 lane，不得退化成无意义狭长走廊或远端 patch 拼接
  - `center_junction` 的理想几何是围绕当前语义中心展开的中心型路口面；可覆盖多个合法 arms，但不得退化成单条带状走廊，也不得依赖 `foreign roads / arms / corridors` 才成立
  - 无意义狭长面、无意义空洞、无意义凹陷、细脖子、非当前方向远端尾巴、依赖 `foreign` 空间的补丁连接，都属于步骤6问题几何
  - 步骤6失败按两层归因冻结为：
    - 一级：`infeasible_under_frozen_constraints`、`geometry_solver_failed`
    - 二级：`step1_step3_conflict`、`stage3_rc_gap`、`foreign_exclusion_conflict`、`template_misfit`、`geometry_closure_failure`、`cleanup_overtrim`、`cleanup_undertrim`、`foreign_reintroduced_by_cleanup`、`shape_artifact_failure`
  - 当前目视检查中唯一已明确确认的失败锚点是 `520394575`；除它之外，若其他 case 要进入步骤6失败归类，必须先完成根因分型
  - Stage3 步骤7「准出判定」中，步骤7是最终裁决层，只基于步骤1到步骤6已冻结结果做 `accepted / review_required / rejected` 分类，不承担补救职责
  - `accepted` 的最小前提是：步骤1 must-cover 成立、步骤3合法活动空间成立、步骤4 `required RC` 成立、步骤5 `foreign` 排除成立、步骤6几何成立且不是问题几何、且不存在未消除的核心审计异常
  - `review_required` 只适用于：当前结果已经满足业务需求，但几何表现、可审查性或视觉质量仍存在风险；`review_required` 只允许映射到 `V2`
- `rejected` 只适用于：当前 case 已明确违反硬规则、或在当前冻结约束下无合法解、或步骤6已经确认“路口面几何未成立”且失败根因已明确；`rejected` 只允许映射到 `V3 / V4 / V5`
- 步骤7不能洗白前面步骤的失败；若步骤6已认定“路口面几何未成立”，步骤7只能在 `review_required / rejected` 之间分类，不能再解释成成功
- Stage3 结果类型与目视分类的正式映射冻结为：
  - `accepted -> V1`
  - `review_required -> V2`
  - `rejected -> V3 / V4 / V5`
- Stage3 / Stage4 的目视检查 PNG 当前统一复用三态样式：
  - `accepted`：正常成功图样式，无整图风险/失败掩膜
  - `review_required`：浅琥珀 / 橙黄色系整图掩膜、深橙粗边框、风险区域橙色强调、显式 `REVIEW / 待复核` 标识
  - `rejected` 或 `success = false`：淡红整图掩膜、深红粗边框、失败区域深红强调、显式 `REJECTED / 失败` 标识
  - `review_required` 不使用红色系主样式；`V2` 必须使用该风险样式；`V3 / V4 / V5` 必须统一使用失败样式
  - 非成功图必须与成功图一眼可区分，且风险态与失败态彼此也必须一眼可区分
- 补充已实现：
  - stage2 新增输入 `RCSDIntersection`
  - stage2 summary 读取 `segment`
  - `nodes.is_anchor`
  - `nodes.anchor_reason`
  - `is_anchor = yes / no / fail1 / fail2 / null`
  - `anchor_reason = roundabout / t / null`
  - `node_error_1 / node_error_2`
  - 单节点多面命中、`kind_2 = 64` 全组命中、`kind_2 = 2048` 全组命中可从原 `fail1` 口径豁免为 `yes`
  - 上述豁免场景不输出 `node_error_1`
  - `node_error_2` 反向包含时先忽视代表 node `kind_2 = 1` 的组；过滤后仅当剩余组数大于 1 时才记 `fail2`
  - `fail2` 仍优先于 `fail1` 与上述豁免
  - `kind_2 in {8,16}` 若满足 Stage2 标准，同样可直接写 `is_anchor = yes`
  - `t02_stage2_summary.json`
  - stage3 `virtual intersection anchoring`
  - `t02-virtual-intersection-poc` 的 `case-package` 与 `full-input` 两种模式
  - 基于 DriveZone / roads / RCSDRoad / RCSDNode 的局部 patch、分支证据和 RC 关联输出
  - full-input 的 `preflight / summary / perf_summary / virtual_intersection_polygons.gpkg / _rendered_maps`
  - 单 / 多 `mainnodeid` 文本证据包导出与解包
- 独立工具补充已实现：
  - `t02-fix-node-error-2` 独立离线修复工具
  - 按 `RCSDIntersection` 面反选 `node_error_2` 候选组
  - `kind_2 = 1` 组忽视但仍作为连通阻断候选
  - 基于 roads 拓扑的组间连通判定与 `nodes_fix.gpkg / roads_fix.gpkg / fix_report.json` 输出
- 未实现：
  - 最终唯一锚定决策闭环
  - 概率 / 置信度
  - 环岛新规则
  - 误伤捞回
  - 正式产线级全量虚拟路口面批处理
