# t02_junction_anchor

> 本文件是 `t02_junction_anchor` 的操作者总览与运行入口说明。长期源事实以 `architecture/*` 与 `INTERFACE_CONTRACT.md` 为准；如本文件与长期源事实表述不一致，以后者为准。

## 1. 模块定位

- T02 是当前已登记的正式业务模块。
- 当前正式实现范围是 stage1 `DriveZone / has_evd gate`。
- 模块长期目标是为双向 Segment 相关路口锚定提供可审计、可复现的下游基础；stage2 锚定主逻辑仍处于占位与后续澄清阶段。

## 2. 官方运行入口

```bash
python -m rcsd_topo_poc t02-stage1-drivezone-gate --help
```

补充：

```bash
python -m rcsd_topo_poc t02-virtual-intersection-poc --help
```

- `t02-virtual-intersection-poc` 是当前为单 `mainnodeid` 虚拟路口面验证新增的实验性 POC 入口
- 它不重算 stage1 `has_evd`，也不替代当前正式的 stage1 基线

## 3. 常见运行方式

```bash
python -m rcsd_topo_poc t02-stage1-drivezone-gate \
  --segment-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.geojson \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/nodes.geojson \
  --drivezone-path /mnt/d/TestData/POC_Data/patch_all/DriveZone.geojson \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_stage1_drivezone_gate \
  --run-id t02_stage1_run
```

POC 示例：

```bash
python -m rcsd_topo_poc t02-virtual-intersection-poc \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T02/stage2/nodes.geojson \
  --roads-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/roads.geojson \
  --drivezone-path /mnt/d/TestData/POC_Data/patch_all/DriveZone.geojson \
  --rcsdroad-path /mnt/d/TestData/POC_Data/patch_all/RCSDRoad.geojson \
  --rcsdnode-path /mnt/d/TestData/POC_Data/patch_all/RCSDNode.geojson \
  --mainnodeid 100 \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_virtual_intersection_poc \
  --run-id t02_virtual_intersection_demo
```

说明：

- `segment` 与 `nodes` 应来自同一轮 T01 成果。
- `DriveZone` 与 `nodes` 会在空间判定前统一到 `EPSG:3857`。
- 官方默认工作输出根目录是 `outputs/_work/t02_stage1_drivezone_gate`。
- 显式传入 `--out-root` 时，其语义也是“工作输出根目录”；最终运行目录固定为 `<out_root>/<run_id>`。

## 4. 输出总览

- `nodes.geojson`
  - 继承输入 `nodes` 字段并新增 `has_evd`
  - 只有代表 node 写 `yes/no`
  - 输出 geometry 统一为 `EPSG:3857`
- `segment.geojson`
  - 继承输入 `segment` 字段并新增 `has_evd`
  - 输出 geometry 统一为 `EPSG:3857`
- `t02_stage1_summary.json`
  - 汇总总计数与按 `s_grade` 分桶的 summary
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
- `virtual_intersection_polygon.geojson`
  - 单 `mainnodeid` POC 生成的虚拟路口面
- `branch_evidence.json`
- `branch_evidence.geojson`
  - 分支方向、证据等级、是否纳入虚拟面和 RC 方向组映射
- `associated_rcsdroad.geojson`
- `associated_rcsdroad_audit.csv`
- `associated_rcsdroad_audit.json`
  - 已关联与未关联的 RCSDRoad 结果及审计
- `associated_rcsdnode.geojson`
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
- `specs/t02-junction-anchor/*` 是变更工件，不是长期模块真相主表面。

## 6. 当前实现范围

- 已实现：
  - stage1 输入读取与严格字段校验
  - `pair_nodes + junc_nodes` 解析与单 `segment` 去重
  - `mainnodeid` 分组 / 单点兜底
  - 代表 node `has_evd` 写值
  - `segment.has_evd`
  - `summary`
  - `audit/log`
  - 单 `mainnodeid` 虚拟路口面 POC
  - 基于 DriveZone / roads / RCSDRoad / RCSDNode 的局部 patch、分支证据和 RC 关联输出
- 未实现：
  - stage2 锚定主逻辑
  - 概率 / 置信度
  - 环岛新规则
  - 误伤捞回
  - 全量虚拟路口面批处理
