# t02_junction_anchor

> 本文件是 `t02_junction_anchor` 的操作者总览与运行入口说明。长期源事实以 `architecture/*` 与 `INTERFACE_CONTRACT.md` 为准；如本文件与长期源事实表述不一致，以后者为准。

## 1. 模块定位

- T02 是当前已登记的正式业务模块。
- 当前正式实现范围包括：
  - stage1 `DriveZone / has_evd gate`
  - stage2 `anchor recognition / anchor existence`
  - stage3 `virtual intersection anchoring`
- 模块长期目标是为双向 Segment 相关路口锚定提供可审计、可复现的下游基础。
- `t02-virtual-intersection-poc` 是当前 stage3 baseline 官方入口。
- 单 `mainnodeid` 文本证据包当前作为 stage3 复核与外部复现支撑工具保留。
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
python -m rcsd_topo_poc t02-decode-text-bundle --help
```

- `t02-virtual-intersection-poc` 是当前 stage3 baseline 官方入口
- 默认 `case-package` 模式保持既有单 `mainnodeid` baseline 回归能力
- 显式 `--input-mode full-input` 时，统一承接：
  - 完整数据 + 指定 `mainnodeid`
  - 完整数据 + 自动识别“有资料但未锚定”的路口
- 它不重算 stage1 `has_evd` 或 stage2 `is_anchor`，而是直接消费其结果字段
- `t02-export-text-bundle` / `t02-decode-text-bundle` 用于单 `mainnodeid` 文本证据包导出与解包，服务于 stage3 复核与外部复现
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

```bash
python -m rcsd_topo_poc t02-virtual-intersection-poc \
  --input-mode full-input \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg \
  --roads-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg \
  --drivezone-path /mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg \
  --rcsdroad-path /mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg \
  --rcsdnode-path /mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg \
  --max-cases 100 \
  --workers 4 \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_virtual_intersection_full_input \
  --run-id t02_virtual_intersection_full_input_demo \
  --debug
```

```bash
python -m rcsd_topo_poc t02-export-text-bundle \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/nodes.gpkg \
  --roads-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/roads.gpkg \
  --drivezone-path /mnt/d/TestData/POC_Data/patch_all/DriveZone.gpkg \
  --rcsdroad-path /mnt/d/TestData/POC_Data/RC4/RCSDRoad.gpkg \
  --rcsdnode-path /mnt/d/TestData/POC_Data/RC4/RCSDNode.gpkg \
  --mainnodeid 765003 \
  --out-txt /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_text_bundle/case_765003.txt
```

```bash
python -m rcsd_topo_poc t02-decode-text-bundle \
  --bundle-txt /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_text_bundle/case_765003.txt
```

说明：

- `segment` 与 `nodes` 应来自同一轮 T01 成果。
- `DriveZone` 与 `nodes` 会在空间判定前统一到 `EPSG:3857`。
- 官方默认工作输出根目录是 `outputs/_work/t02_stage1_drivezone_gate`。
- 显式传入 `--out-root` 时，其语义也是“工作输出根目录”；最终运行目录固定为 `<out_root>/<run_id>`。

## 4. 输出总览

补充：
- `--debug-render-root` 仅控制 debug 叠图 PNG 的批次归档位置，不改变正式运行目录 `<out_root>/<run_id>`。

- `nodes.gpkg`
  - 继承输入 `nodes` 字段并新增 `has_evd`
  - 只有代表 node 写 `yes/no`
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
- `virtual_intersection_polygon.gpkg`
  - stage3 单 case 生成的虚拟路口面
- `virtual_intersection_polygons.gpkg`
  - stage3 full-input 模式汇总生成的批次虚拟路口面图层
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
- 内含 `manifest.json`、`drivezone_mask.png`、`drivezone.gpkg`、`nodes.gpkg`、`roads.gpkg`、`rcsdroad.gpkg`、`rcsdnode.gpkg`、`size_report.json`
- `t02-decode-text-bundle` 默认解包到与 bundle 同目录、且以 bundle 文件名为目录名的子目录；例如 `case_765003.txt -> case_765003/`
  - 导出时强制检查最终文本体积 `<= 300KB`；超限时失败并输出体积分析报告

说明：

- stage1 业务 summary 的分桶继续按 `0-0双 / 0-1双 / 0-2双` 统计。
- stage1 在分桶之外补充 `all__d_sgrade`，表示所有 `s_grade` 非空的 `segment` 总汇总。
- stage1 同时补充 `summary_by_kind_grade`，固定输出 `kind2_4_64_grade2_1 / kind2_4_64_grade2_0_2_3 / kind2_2048 / kind2_8_16` 四个 bucket，并按目标路口唯一 `junction_id` 统计 `junction_count / junction_has_evd_count`。

## 5. 文档阅读顺序

1. `architecture/01-introduction-and-goals.md`
2. `architecture/02-constraints.md`
3. `architecture/04-solution-strategy.md`
4. `architecture/05-building-block-view.md`
5. `INTERFACE_CONTRACT.md`
6. `architecture/10-quality-requirements.md`

补充：

- `architecture/overview.md` 用于快速总览和索引，不替代标准 architecture 文档组。
- `history/*` 保留阶段演进记录，不替代当前正式源事实。
- `specs/t02-junction-anchor/*` 与 `specs/t02-virtual-intersection-batch-poc/*` 是变更工件，不是长期模块真相主表面。

## 6. 当前实现范围

- 已实现：
  - stage1 输入读取与严格字段校验
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
  - `yes / no / fail1 / fail2 / null`
  - `node_error_1 / node_error_2`
  - `fail2` 优先于 `fail1`
  - `t02_stage2_summary.json`
  - stage3 `virtual intersection anchoring`
  - `t02-virtual-intersection-poc` 的 `case-package` 与 `full-input` 两种模式
  - 基于 DriveZone / roads / RCSDRoad / RCSDNode 的局部 patch、分支证据和 RC 关联输出
  - full-input 的 `preflight / summary / perf_summary / virtual_intersection_polygons.gpkg / _rendered_maps`
  - 单 `mainnodeid` 文本证据包导出与解包
- 未实现：
  - 最终唯一锚定决策闭环
  - 概率 / 置信度
  - 环岛新规则
  - 误伤捞回
  - 正式产线级全量虚拟路口面批处理
