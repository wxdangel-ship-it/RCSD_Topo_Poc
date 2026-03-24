# T02 - INTERFACE_CONTRACT

## 定位

- 本文件是 `t02_junction_anchor` 的稳定契约面。
- 模块目标、上下文、构件关系与风险说明以 `architecture/*` 为准。
- `README.md` 只承担操作者入口职责，不替代长期源事实。

## 1. 目标与范围

- 模块 ID：`t02_junction_anchor`
- 长期目标：
  - 为双向 Segment 相关路口锚定提供稳定、可审计的下游模块基础
- 当前正式范围：
  - stage1 `DriveZone / has_evd gate`
  - 消费 T01 `segment` 与 `nodes`
  - 产出 `nodes.has_evd`、`segment.has_evd`、`summary`、`audit/log`
- 当前不在正式范围：
  - stage2 锚定主逻辑
  - 最终锚定结果与几何表达
  - 候选生成 / 候选打分
  - 概率 / 置信度实现
  - 误伤捞回
  - 环岛新业务规则

## 2. Inputs

### 2.1 必选输入

- `segment`
- `nodes`
- `DriveZone.geojson`

### 2.2 可选输入兼容参数

- `segment_layer`
- `nodes_layer`
- `drivezone_layer`
- `segment_crs`
- `nodes_crs`
- `drivezone_crs`

说明：

- 对 GeoJSON，若源文件缺失 CRS，则必须显式传入对应 CRS override，否则执行失败。
- 对 Shapefile，若无 `.prj`，也必须显式传入对应 CRS override，否则执行失败。

### 2.3 输入前提

- `segment` 与 `nodes` 必须来自同一轮、可相互追溯的 T01 成果。
- `segment` 必须具备：
  - `id`
  - `pair_nodes`
  - `junc_nodes`
  - `s_grade` 或 `sgrade`
- `nodes` 必须具备：
  - `id`
  - `mainnodeid`
  - 可用 geometry
- `DriveZone` 必须具备可用于“落入或边界接触”判断的面状 geometry。
- `nodes` 与 `DriveZone` 在空间判定前必须统一到 `EPSG:3857`。
- 当前实现为保持输出一致性，也会将 `segment` 输出 geometry 统一写到 `EPSG:3857`。

### 2.4 实际输入字段冻结

#### `segment`

- 主键字段：`id`
- 路口字段：`pair_nodes`
- 路口字段：`junc_nodes`
- 分桶逻辑字段：`s_grade` 或 `sgrade`

#### `nodes`

- 主键字段：`id`
- junction 分组字段：`mainnodeid`

说明：

- 文档中仍可使用“mainnode”作为业务概念名。
- stage1 实际输入字段冻结为 `mainnodeid`。
- `working_mainnodeid` 不作为 stage1 正式输入字段。
- `s_grade / sgrade` 是输入兼容映射，不代表要求 T01 改历史产物。

### 2.5 Stage1 处理契约

- 路口来源：
  - 只认 `pair_nodes` 与 `junc_nodes`
- 单 `segment` 去重：
  - 先解析 `pair_nodes + junc_nodes`
  - 再在单个 `segment` 内去重
- 路口组装：
  1. 先查 `mainnodeid = J`
  2. 若不存在，再查 `mainnodeid = NULL 且 id = J`
- 代表 node：
  - 若 `mainnodeid = J` 成组，则组内 `id = J` 的 node 为代表 node
  - 若代表 node 缺失，记 `representative_node_missing`，不允许 fallback
  - 环岛场景当前继承 T01 既有逻辑，不由 T02 自行扩写
- DriveZone 判定：
  - `nodes` 与 `DriveZone` 在 `EPSG:3857` 下做空间关系判断
  - 任一组内 node 落入或接触 `DriveZone` 边界，即 `has_evd = yes`
- 路口组不存在：
  - 记 `junction_nodes_not_found`
  - 业务结果按 `has_evd = no`
- 空目标路口 `segment`：
  - `segment.has_evd = no`
  - `reason = no_target_junctions`
- `segment.has_evd`：
  - 只有去重后的全部目标路口都为 `yes`，才记 `yes`
- `summary`：
  - 仅按 `0-0双 / 0-1双 / 0-2双` 分桶
  - 桶内路口按唯一 ID 统计，不按 `segment-路口` 展开重复计数

## 3. Outputs

### 3.1 官方输出目录

- 官方默认工作输出根目录为：

```text
outputs/_work/t02_stage1_drivezone_gate
```

- 若显式传入 `--out-root`，其语义也是“工作输出根目录”。
- 无论是否显式传入 `--out-root`，本次运行的最终输出目录都固定为：

```text
<out_root>/<run_id>
```

- stage1 的官方工作输出应落在 repo `outputs/_work/` 体系下；若因受控集成场景需要显式覆盖 `--out-root`，也必须保持 `run_id` 叶子目录隔离。

### 3.2 正式输出文件

- `nodes.geojson`
- `segment.geojson`
- `t02_stage1_summary.json`
- `t02_stage1_audit.csv`
- `t02_stage1_audit.json`
- `t02_stage1.log`
- `t02_stage1_progress.json`
- `t02_stage1_perf.json`
- `t02_stage1_perf_markers.jsonl`

### 3.3 输出语义

#### `nodes.geojson`

- 继承输入 `nodes` properties
- 新增字段：`has_evd`
- 值域：`yes / no / null`
- 只有代表 node 写 `yes/no`
- 非代表 node 保持 `null`
- 输出 geometry CRS：`EPSG:3857`

#### `segment.geojson`

- 继承输入 `segment` properties
- 新增字段：`has_evd`
- 值域：`yes / no`
- 输出 geometry CRS：`EPSG:3857`

#### `t02_stage1_summary.json`

- 包含：
  - `run_id`
  - `success`
  - `target_crs`
  - `inputs`
  - `counts`
  - `summary_by_s_grade`
  - `output_files`
- `summary_by_s_grade` 每桶至少包含：
  - `segment_count`
  - `segment_has_evd_count`
  - `junction_count`
  - `junction_has_evd_count`

#### `t02_stage1_audit.csv / t02_stage1_audit.json`

- 稳定字段：
  - `scope`
  - `segment_id`
  - `junction_id`
  - `status`
  - `reason`
  - `detail`
- 当前冻结 reason：
  - `junction_nodes_not_found`
  - `representative_node_missing`
  - `no_target_junctions`
  - `missing_required_field`
  - `invalid_crs_or_unprojectable`

#### `t02_stage1.log`

- 记录运行开始、输入读取、关键计数与输出目录

#### `t02_stage1_progress.json`

- 当前运行阶段快照
- 至少包含：
  - `run_id`
  - `status`
  - `updated_at`
  - `current_stage`
  - `message`
  - `counts`

#### `t02_stage1_perf.json`

- 本次运行的性能摘要
- 至少包含：
  - `run_id`
  - `success`
  - `total_wall_time_sec`
  - `counts`
  - `stage_timings`

#### `t02_stage1_perf_markers.jsonl`

- 阶段级性能标记流
- 每条记录至少包含：
  - `event`
  - `run_id`
  - `at`
  - `stage`
  - `elapsed_sec`
  - `counts`

## 4. EntryPoints

### 4.1 官方入口

```bash
python -m rcsd_topo_poc t02-stage1-drivezone-gate --help
```

### 4.2 实验性 POC 入口

```bash
python -m rcsd_topo_poc t02-virtual-intersection-poc --help
```

- `t02-virtual-intersection-poc` 只处理单个 `mainnodeid`
- 当前定位是实验性 POC，不替代正式 stage1 基线
- 该入口直接消费带 `has_evd / is_anchor` 的 `nodes`，不会在入口内部重算 stage1 / stage2 主逻辑

### 4.3 程序内入口

- [stage1_drivezone_gate.py](/mnt/e/Work/RCSD_Topo_Poc/src/rcsd_topo_poc/modules/t02_junction_anchor/stage1_drivezone_gate.py)
  - `run_t02_stage1_drivezone_gate(...)`
  - `run_t02_stage1_drivezone_gate_cli(args)`
- `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py`
  - `run_t02_virtual_intersection_poc(...)`
  - `run_t02_virtual_intersection_poc_cli(args)`

## 5. Params

### 5.1 关键参数类别

- 输入路径：
  - `segment_path`
  - `nodes_path`
  - `drivezone_path`
- 输入兼容参数：
  - `segment_layer`
  - `nodes_layer`
  - `drivezone_layer`
  - `segment_crs`
  - `nodes_crs`
  - `drivezone_crs`
- 输出控制：
  - `out_root`
  - `run_id`

### 5.2 实验性 POC 参数

- 必选输入：
  - `nodes_path`
  - `roads_path`
  - `drivezone_path`
  - `rcsdroad_path`
  - `rcsdnode_path`
  - `mainnodeid`
- 可选兼容：
  - `nodes_layer / roads_layer / drivezone_layer / rcsdroad_layer / rcsdnode_layer`
  - `nodes_crs / roads_crs / drivezone_crs / rcsdroad_crs / rcsdnode_crs`
- 可选 patch 控制：
  - `buffer_m`
  - `patch_size_m`
  - `resolution_m`
- 输出控制：
  - `out_root`
  - `run_id`

### 5.3 参数原则

- 所有输入兼容都必须显式声明；不能猜字段、猜 CRS、猜 fallback。
- stage1 当前没有业务阈值参数，也不开放 stage2 相关参数。
- 本文件只固化长期参数类别与语义，不复制完整 CLI 参数表。

## 6. Examples

```bash
python -m rcsd_topo_poc t02-stage1-drivezone-gate \
  --segment-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.geojson \
  --nodes-path /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/nodes.geojson \
  --drivezone-path /mnt/d/TestData/POC_Data/patch_all/DriveZone.geojson \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t02_stage1_drivezone_gate \
  --run-id t02_stage1_run
```

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

### 6.1 实验性 POC 输入前提

- `nodes` 必须包含：`id / mainnodeid / has_evd / is_anchor / kind_2 / grade_2`
- `roads` 与 `RCSDRoad` 当前只依赖：`id / snodeid / enodeid / direction`
- `RCSDNode` 必须包含：`id / mainnodeid`
- `mainnodeid` 对应代表 node 必须满足：`has_evd = yes`、`is_anchor = no`、`kind_2 in {4, 2048}`
- `RCSDRoad / RCSDNode` 在局部 patch 内若不落在 `DriveZone` 上，入口必须失败并输出审计

## 7. Acceptance

1. 官方入口可稳定产出 `nodes.geojson`、`segment.geojson`、`summary`、`audit`、`log`。
2. `has_evd` 保持 `yes/no/null` 业务语义，不偷换为布尔值或 `0/1`。
3. 缺字段、缺 CRS、代表 node 缺失、路口组缺失、空目标路口等情形都可被诊断。
4. stage2 字段、概率/置信度与环岛新规则未泄漏进当前正式契约。
