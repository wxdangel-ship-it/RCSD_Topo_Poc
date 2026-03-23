# t02_junction_anchor

> 本文件是 `t02_junction_anchor` 的操作者总览与运行入口说明。长期源事实以 `architecture/*` 与 `INTERFACE_CONTRACT.md` 为准；如本文件与长期源事实表述不一致，以后者为准。

## 1. 模块定位

- T02 是当前已登记的正式业务模块。
- 当前正式实现范围是 stage1 `DriveZone / has_evd gate`。
- 模块长期目标是为双向 Segment 相关路口锚定提供可审计、可复现的下游基础。
- 当前文档基线已覆盖 stage2 anchor recognition / anchor existence；当前代码已实现最小闭环，但尚未进入最终唯一锚定决策与概率阶段。

## 2. 官方运行入口

```bash
python -m rcsd_topo_poc t02-stage1-drivezone-gate --help
```

```bash
python -m rcsd_topo_poc t02-stage2-anchor-recognition --help
```

## 3. 常见运行方式

```bash
python -m rcsd_topo_poc t02-stage1-drivezone-gate \
  --segment-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.geojson \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/nodes.geojson \
  --drivezone-path /mnt/d/TestData/POC_Data/patch_all/DriveZone.geojson \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_stage1_drivezone_gate \
  --run-id t02_stage1_run
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
  - 汇总总计数、按 `s_grade` 分桶的 summary、`all__d_sgrade`，以及按代表 node.kind 分级的 `summary_by_kind`
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

说明：

- stage1 业务 summary 的分桶继续按 `0-0双 / 0-1双 / 0-2双` 统计。
- stage1 在分桶之外补充 `all__d_sgrade`，表示所有 `s_grade` 非空的 `segment` 总汇总。
- stage1 同时补充 `summary_by_kind`，固定输出 `kind_4_64 / kind_2048 / kind_8_16` 三个 bucket，并按目标路口唯一 `junction_id` 统计 `junction_count / junction_has_evd_count`。

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
- 已实现：
  - stage2 新增输入 `RCSDIntersection.geojson`
  - `nodes.is_anchor`
  - `yes / no / fail1 / fail2 / null`
  - `node_error_1 / node_error_2`
  - `fail2` 优先于 `fail1`
- 未实现：
  - 最终唯一锚定决策闭环
  - 概率 / 置信度
  - 环岛新规则
  - 误伤捞回
