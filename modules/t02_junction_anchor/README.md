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
- `t02-stage4-divmerge-virtual-polygon` 用于单 case 的 div/merge 虚拟路口面 baseline，输入为 `nodes / roads / DriveZone / DivStripZone / RCSDRoad / RCSDNode / mainnodeid`，处理范围覆盖 `kind_2 in {8, 16}` 以及 `kind / kind_2 = 128` 的复杂路口主节点
- `t02-aggregate-continuous-divmerge` 是独立离线聚合工具，按 T04 continuous chain 语义识别连续分歧/合流组，改写 `nodes / roads` 并输出 `nodes_fix.gpkg / roads_fix.gpkg / continuous_divmerge_report.json`
- 该工具会同步输出：
  - 新生成复杂路口数量 `complex_junction_count`
  - 新生成复杂路口 `mainnodeid` 列表 `complex_mainnodeids`
  - CLI 结束时也会直接打印这两个摘要
- T02 当前输入兼容 `GeoPackage(.gpkg)`、`GeoJSON` 与 `Shapefile`；历史 `.gpkt` 后缀仅做兼容读取；若同名 `.gpkg` 与 `.geojson` 同时存在，默认优先读取 `GeoPackage`
- T02 当前矢量输出统一写为 `GeoPackage(.gpkg)`；文本证据包仍输出单个 txt，但解包后的矢量文件也统一为 `.gpkg`
- `case-package` 是 stage3 baseline regression 入口，不允许回退
- `full-input` 是 stage3 完整数据 baseline 入口；共享大图层直连运行必须先满足正确 layer / CRS / 预裁剪与 preflight 约束
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

- 自动发现只处理符合 Stage4 baseline 的代表 node：`has_evd = yes`、`is_anchor = no`，且 `kind_2 in {8, 16}` 或 `kind / kind_2 = 128`。
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
- `virtual_intersection_polygons.gpkg`
  - stage3 full-input 模式汇总生成的批次虚拟路口面图层
- `stage4_virtual_polygon.gpkg`
  - stage4 单 case 生成的 div/merge 虚拟路口面
- `stage4_node_link.json`
  - stage4 与 `nodes.mainnodeid` 的关联结果
- `stage4_rcsdnode_link.json`
  - stage4 与 `RCSDNode` seed / 相关 node 的关联结果
- `stage4_audit.json`
  - stage4 审计结果
- `_rendered_maps/`
  - stage3 批次 render 目录
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

- stage1 正式候选边界已扩到 `semantic_junction_set ∪ segment_referenced_junction_set`。
- stage1 业务 summary 的 `summary_by_s_grade` 继续按 `0-0双 / 0-1双 / 0-2双` 的 segment 视图统计。
- stage1 在分桶之外补充 `all__d_sgrade`，表示所有 `s_grade` 非空的 `segment` 总汇总。
- stage1 同时补充 `summary_by_kind_grade`，固定输出 `kind2_4_64_grade2_1 / kind2_4_64_grade2_0_2_3 / kind2_2048 / kind2_8_16` 四个 bucket，并按 `stage1_candidate_junction_set` 唯一 `junction_id` 统计 `junction_count / junction_has_evd_count`。
- stage2 正式候选边界同样扩到 `semantic_junction_set ∪ segment_referenced_junction_set`，但 `summary_by_s_grade` 仍保持 segment 视图。
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
  - `semantic_junction_set ∪ segment_referenced_junction_set` 候选扩展
  - `pair_nodes + junc_nodes` 解析与单 `segment` 去重
  - `mainnodeid` 分组 / 单点兜底
  - 代表 node `has_evd` 写值
  - `segment.has_evd`
  - `summary`
  - `audit/log`
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
