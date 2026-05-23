# T07 - INTERFACE_CONTRACT

## 定位

本文件是 `t07_semantic_junction_anchor` 的稳定接口契约。T07 当前只覆盖语义路口级 Step1 / Step2：

- Step1：基于 `nodes` 与 `DriveZone` 判定代表 node 的 `has_evd`。
- Step2：基于 `nodes` 与 `RCSDIntersection` 判定代表 node 的 `is_anchor / anchor_reason`。

本模块不处理 Segment，不生成虚拟路口面，不执行最终唯一锚定决策。

## 1. 目标与范围

### 1.1 当前正式支持

- 消费 `nodes.gpkg`、`DriveZone.gpkg` 与 `RCSDIntersection.gpkg`。
- 按 `nodes.mainnodeid` 组装 SWSD 语义路口；`mainnodeid` 为空时退化为单 node 语义路口。
- 以语义路口代表 node 的 `kind_2` 作为 Step1 / Step2 类型 gate。
- 仅对代表 node `kind_2 in {4, 8, 16, 64, 128, 2048}` 的语义路口处理 `has_evd`。
- 仅对代表 node `has_evd = yes` 的语义路口处理 `is_anchor / anchor_reason`。
- 只对代表 node 写 `has_evd / is_anchor / anchor_reason`。
- 保留 T02 Step2 的空间命中、`fail1 / fail2` 与 `roundabout / t` 原因语义。

### 1.2 当前非目标

- 不读取或输出 `segment.gpkg`。
- 不解析 `pair_nodes / junc_nodes`。
- 不输出 `segment.has_evd`。
- 不生成 Segment 视角 summary。
- 不执行 T02 Stage3 virtual intersection anchoring。
- 不执行 T02 Stage4 div/merge virtual polygon。
- 不新增 repo CLI、`tools`、`Makefile`、模块 `run.py` 或模块 `__main__.py`。
- 除已登记的 `scripts/t07_run_semantic_junction_anchor_innernet.sh` 外，不新增其它 repo 级脚本入口。

## 2. Inputs

### 2.1 Step1 输入

必选输入：

- `nodes_path`：SWSD `nodes.gpkg`。
- `drivezone_path`：`DriveZone.gpkg`。
- `out_root`：输出根目录。

`nodes` 依赖字段：

- `id`
- `mainnodeid`
- `kind_2`
- geometry

`DriveZone` 依赖：

- 面状 geometry。

### 2.2 Step2 输入

必选输入：

- `nodes_path`：Step1 输出或等价字段完备的 `nodes.gpkg`。
- `intersection_path`：`RCSDIntersection.gpkg`。
- `out_root`：输出根目录。

`nodes` 依赖字段：

- `id`
- `mainnodeid`
- `kind_2`
- `has_evd`
- geometry

`RCSDIntersection` 依赖：

- 面状 geometry。
- 可选 `id / intersection_id / intersectionid / fid / objectid / OBJECTID` 作为审计标识。

### 2.3 输入前提

- 所有空间判定必须在统一 CRS 下完成，目标处理 CRS 为 `EPSG:3857`。
- GeoJSON 若缺失 CRS，必须显式传入 CRS override；Shapefile 若缺少 `.prj`，必须显式传入 CRS override。
- 缺失必需字段、缺失 CRS、无法投影或 geometry 不可用时，必须显式失败并留审计，不得转换成业务 `no`。
- `kind_2` 是当前唯一正式类型字段；不读取 `Kind_2`。
- `mainnodeid` 按 T02 口径组装：非空值成组，空值按 `id` singleton fallback。若后续需要把 `0` 视为空值，必须另行确认并同步契约。

## 3. Business Rules

### 3.1 语义路口组装

- 若存在 `mainnodeid = J` 的 node 集合，则这些 node 构成语义路口 `J`。
- 语义路口 `J` 的代表 node 必须满足 `id = J`。
- 若成组后缺少 `id = J` 的代表 node，记录 `representative_node_missing`，不得 fallback。
- 若 node 的 `mainnodeid` 为空，则该 node 自身构成 singleton 语义路口。
- `has_evd / is_anchor / anchor_reason` 只写代表 node。

### 3.2 Step1 `has_evd`

- 代表 node `kind_2` 不在 `{4, 8, 16, 64, 128, 2048}` 时：
  - `has_evd = NULL`
  - `is_anchor = NULL`
  - `anchor_reason = NULL`
  - 不进入 Step2
- 代表 node `kind_2 in {4, 8, 16, 64, 128, 2048}` 时：
  - 任一组内 node 落入或接触 `DriveZone`，代表 node `has_evd = yes`
  - 组内所有 node 均未命中 `DriveZone`，代表 node `has_evd = no`
- 边界接触视为命中。

### 3.3 Step2 `is_anchor / anchor_reason`

- 仅代表 node `has_evd = yes` 的语义路口进入 Step2 主判定域。
- `has_evd != yes` 的语义路口：
  - `is_anchor = NULL`
  - `anchor_reason = NULL`
- 若组内所有 node 均未落入或接触任何 `RCSDIntersection`：
  - `is_anchor = no`
  - `anchor_reason = NULL`
- 若命中唯一 `RCSDIntersection`：
  - `is_anchor = yes`
  - `anchor_reason = NULL`
- 单节点语义路口命中多个 `RCSDIntersection`：
  - `is_anchor = yes`
  - `anchor_reason = NULL`
  - 不输出 `node_error_1`
- `kind_2 = 64` 且组内所有 node 均命中任意 `RCSDIntersection`：
  - `is_anchor = yes`
  - `anchor_reason = roundabout`
  - 不输出 `node_error_1`
- `kind_2 = 2048` 且组内所有 node 均命中任意 `RCSDIntersection`：
  - `is_anchor = yes`
  - `anchor_reason = t`
  - 不输出 `node_error_1`
- 对未命中上述豁免规则的多节点组，若同一组 node 命中两个及以上不同 `RCSDIntersection`：
  - `is_anchor = fail1`
  - `anchor_reason = NULL`
  - 输出 `node_error_1`
- 若一个 `RCSDIntersection` 面对应多个参与 Step2 的语义路口：
  - 先忽略代表 node `kind_2 = 1` 的组
  - 过滤后剩余组数大于 `1` 时，相关代表 node `is_anchor = fail2`
  - 输出 `node_error_2`
- 优先级：
  - `fail2 > fail1`
  - 被 `fail2` 覆盖时，`anchor_reason = NULL`

## 4. Outputs

### 4.1 Step1 输出

目录：

```text
<out_root>/<run_id>/step1_has_evd/
```

文件：

- `nodes.gpkg`
- `t07_step1_summary.json`
- `t07_step1_audit.csv/json`
- `t07_step1_perf.json`

Step1 summary 至少记录：

- `semantic_junction_count`
- `processed_kind2_count`
- `skipped_kind2_count`
- `has_evd_yes_count`
- `has_evd_no_count`
- `has_evd_null_count`
- `representative_missing_count`
- `input_paths`
- `output_paths`
- `target_crs`

### 4.2 Step2 输出

目录：

```text
<out_root>/<run_id>/step2_anchor_recognition/
```

文件：

- `nodes.gpkg`
- `node_error_1.gpkg/csv/json`
- `node_error_2.gpkg/csv/json`
- `t07_step2_summary.json`
- `t07_step2_audit.csv/json`
- `t07_step2_perf.json`

Step2 summary 至少记录：

- `semantic_junction_count`
- `stage2_candidate_count`
- `anchor_yes_count`
- `anchor_no_count`
- `anchor_fail1_count`
- `anchor_fail2_count`
- `anchor_null_count`
- `roundabout_reason_count`
- `t_reason_count`
- `input_paths`
- `output_paths`
- `target_crs`

## 5. EntryPoints

T07 当前不新增 repo 官方 CLI。稳定执行面为模块内 callable runner，并由已登记的内网脚本包装。

Callable runner：

```python
from rcsd_topo_poc.modules.t07_semantic_junction_anchor import (
    run_t07_step1_has_evd,
    run_t07_step2_anchor_recognition,
    run_t07_semantic_junction_anchor,
)
```

内网脚本：

```bash
scripts/t07_run_semantic_junction_anchor_innernet.sh
```

说明：

- 脚本默认读取内网 `nodes / DriveZone / RCSDIntersection` 路径，可通过 `NODES_PATH / DRIVEZONE_PATH / INTERSECTION_PATH` 覆盖。
- 脚本可通过 `NODES_LAYER / DRIVEZONE_LAYER / INTERSECTION_LAYER` 与 `NODES_CRS / DRIVEZONE_CRS / INTERSECTION_CRS` 覆盖图层名和 CRS。
- 脚本不接受 `SEGMENT_PATH`，不读取、不生成、不统计 Segment。
- 若后续要新增 repo CLI、其它 repo 级脚本、`tools/`、模块 `run.py` 或模块 `__main__.py`，必须另行获得用户授权，并同步 `docs/repository-metadata/entrypoint-registry.md`。

## 6. Params

- `run_id`：可选运行 ID；为空时自动生成。
- `nodes_layer / drivezone_layer / intersection_layer`：可选图层名。
- `nodes_crs / drivezone_crs / intersection_crs`：可选 CRS override。

## 7. Acceptance

1. Step1 可在无 Segment 输入下独立计算语义路口级 `has_evd`。
2. Step2 可在无 Segment 输入下独立计算语义路口级 `is_anchor / anchor_reason`。
3. `kind_2` 仅使用代表 node 字段，且仅处理 `{4, 8, 16, 64, 128, 2048}`。
4. 非处理范围 `kind_2` 的 `has_evd / is_anchor / anchor_reason` 均为 `NULL`。
5. 从属 node 不写业务状态。
6. `fail2` 优先于 `fail1`。
7. 所有 CRS、字段、几何、代表 node 缺失问题都有明确审计。
8. 输出不包含 Segment 工件或 Segment 视角 summary。
