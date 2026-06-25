# T07 - INTERFACE_CONTRACT

## 定位

本文件是 `t07_semantic_junction_anchor` 的稳定接口契约。T07 当前覆盖语义路口级 Step1 / Step2，并保留可选独立 Step3 relation 补锚：

- Step1：基于 `nodes` 与 `DriveZone` 判定代表 node 的 `has_evd`；处理范围内语义路口必须组内所有 node 均命中道路面或满足 `1.5m` evidence 面容差才写 `yes`。`RCSDIntersection` 不参与 Step1 `has_evd` 正向判定。
- Step2：基于 `nodes` 与 `RCSDIntersection` 判定代表 node 的 `is_anchor / anchor_reason`。
- Step3：基于 Step2 后 `nodes`、早期或外部方案产出的 `intersection_match_all.geojson` 兼容 relation 文件与输入 `RCSDNode`，对候选 SWSD 语义路口补写 `is_anchor = yes`；它不是 T07 主链对 T05 relation 的强制回灌。
- Step2 / Step3 同步维护 T07 版 handoff 成果 `t07_rcsdintersection_anchor_surface.gpkg` 与 `t07_swsd_rcsd_relation_evidence.csv/json`；Step3 surface 产物直接复制 Step2 结果。

本模块不处理 Segment，不生成虚拟路口面，不执行最终唯一锚定决策。

## 1. 目标与范围

### 1.1 当前正式支持

- Step1/2 消费 `nodes.gpkg`、`DriveZone.gpkg`、`RCSDIntersection.gpkg` 与可选输入 `RCSDNode.gpkg`；其中 Step1 `has_evd` 只使用 `DriveZone`，Step2 `is_anchor` 使用 `RCSDIntersection`。Step3 可选消费 `intersection_match_all.geojson` 兼容 relation 文件与输入 `RCSDNode.gpkg`。
- 按 `nodes.mainnodeid` 组装 SWSD 语义路口；`mainnodeid` 为空时退化为单 node 语义路口。
- 以语义路口代表 node 的 `kind_2` 作为 Step1 / Step2 类型 gate。
- 仅对代表 node `kind_2 in {4, 8, 16, 64, 128, 2048}` 的语义路口处理 `has_evd`。
- 仅对代表 node `has_evd = yes` 的语义路口处理 `is_anchor / anchor_reason`。
- 只对代表 node 写 `has_evd / is_anchor / anchor_reason`。
- 保留 T02 Step2 的空间命中与 `fail1 / fail2` 冲突语义；`kind_2 = 64 / 128 / 2048` 采用 T07 专属 Step2 分流规则，其中 `2048` 只有满足严格 single-surface / single-SWSD / single-RCSD 条件时才建立 Step2 surface 关系，否则保留给 T03/T04 虚拟锚定或 Step3 可选兼容 relation 补锚。
- Step2 输出 `t07_rcsdintersection_anchor_surface.gpkg` 与 `t07_swsd_rcsd_relation_evidence.csv/json`，对应 T02 `t02_rcsdintersection_anchor_surface.gpkg` 与 `t02_swsd_rcsd_relation_evidence.csv/json` 的语义路口级 handoff 口径。
- Step3 的 Step2 surface 1V1 推导处理代表 node `kind_2 in {4, 8, 16, 2048}`；兼容 relation 补充候选处理代表 node `kind_2 in {4, 8, 16, 128, 2048}`，其中 `128` 只允许在兼容 relation 文件已发布 `status = 0 / base_id != 0` 成功 relation 且 RCSD base 存在时补写 `is_anchor = yes`，`2048` 未被 strict Step2 surface 锚定时也可走该补锚路径。
- Step3 只接受 `intersection_match_all.geojson` 兼容 relation 文件中 `status = 0` 且 `base_id != 0` 的成功 relation，并要求 `base_id` 在输入 `RCSDNode.id/mainnodeid` 中存在且未被 Step2 surface 1V1 阶段占用。
- Step3 输出 `t07_rcsdintersection_anchor_surface.gpkg`，内容赋值 Step2 surface 结果；输出合并 Step2 evidence 与 Step3 成功补锚 relation 的 `t07_swsd_rcsd_relation_evidence.csv/json`，并在顶层记录 `anchor_counts.step2_anchor_count / step3_anchor_count / total_anchor_count`。

### 1.2 当前非目标

- 不读取或输出 `segment.gpkg`。
- 不解析 `pair_nodes / junc_nodes`。
- 不输出 `segment.has_evd`。
- 不生成 Segment 视角 summary。
- 不执行 T02 Stage3 virtual intersection anchoring。
- 不执行 T02 Stage4 div/merge virtual polygon。
- 不新增 repo CLI、`tools`、`Makefile`、模块 `run.py` 或模块 `__main__.py`。
- 除已登记的 `scripts/t07_run_semantic_junction_anchor_innernet.sh` 与 `scripts/t07_run_step3_intersection_match_innernet.sh` 外，不新增其它 repo 级脚本入口。

## 2. Inputs

### 2.1 Step1 输入

必选输入：

- `nodes_path`：SWSD `nodes.gpkg`。
- `drivezone_path`：`DriveZone.gpkg`。
- `intersection_path`：`RCSDIntersection.gpkg`；组合 runner 与内网脚本必须传入，Step1 standalone callable 为兼容历史调用可省略。
- `out_root`：输出根目录。

`nodes` 依赖字段：

- `id`
- `mainnodeid`
- `kind_2`
- geometry

`DriveZone` 依赖：

- 面状 geometry。

`RCSDIntersection` 依赖：

- 面状 geometry。

### 2.2 Step2 输入

必选输入：

- `nodes_path`：Step1 输出或等价字段完备的 `nodes.gpkg`。
- `intersection_path`：`RCSDIntersection.gpkg`。
- `out_root`：输出根目录。

可选输入：

- `rcsdnode_path`：RCSD `RCSDNode.gpkg`。启用后，Step2 对命中的 `RCSDIntersection` 面执行可消费性校验：面内必须覆盖至少一个具有可用 `id/mainnodeid` 的 RCSDNode geometry，才允许作为 `is_anchor = yes` 的依据。

`nodes` 依赖字段：

- `id`
- `mainnodeid`
- `kind_2`
- `has_evd`
- geometry

`RCSDIntersection` 依赖：

- 面状 geometry。
- 可选 `id / intersection_id / intersectionid / fid / objectid / OBJECTID` 作为审计标识。

### 2.3 Step3 输入

必选输入：

- `nodes_path`：Step2 输出或等价字段完备的 SWSD `nodes.gpkg`。
- `intersection_match_all_path`：早期或外部方案产出的 `intersection_match_all.geojson` 兼容 relation 文件；T05 Phase2 产物只能作为显式兼容输入。
- `rcsdnode_path`：输入 RCSD `RCSDNode.gpkg`。
- `out_root`：输出根目录。

`nodes` 依赖字段：

- `id`
- `mainnodeid`
- `kind_2`
- `has_evd`
- `is_anchor`
- `anchor_reason`
- geometry

`intersection_match_all.geojson` 依赖字段遵循兼容 relation schema：

- `target_id`：SWSD 语义路口 id。
- `base_id`：RCSD 语义路口主 node id；失败关系为 `0`。
- `status`：`0` 表示成功 relation，`1` 表示失败 relation。
- `level`
- `is_highway`

`RCSDNode` 依赖字段：

- `id`
- 可选 `mainnodeid`

### 2.3 输入前提

- 所有空间判定必须在统一 CRS 下完成，目标处理 CRS 为 `EPSG:3857`。
- GeoJSON 若缺失 CRS，必须显式传入 CRS override；Shapefile 若缺少 `.prj`，必须显式传入 CRS override。
- 缺失必需字段、缺失 CRS、无法投影或 geometry 不可用时，必须显式失败并留审计，不得转换成业务 `no`。
- `kind_2` 是当前唯一正式类型字段；不读取 `Kind_2`。
- `mainnodeid` 按 T02 口径组装：非空值成组，空值按 `id` singleton fallback。若后续需要把 `0` 视为空值，必须另行确认并同步契约。
- T07 对外 handoff 主键字段必须输出 canonical ID：字符串化整数浮点如 `"622700016.0"` 必须归一为 `"622700016"`；非整数小数与非数字业务字符串不得静默误转。
- Step3 输出 `intersection_match_t07.geojson` 采用兼容 relation 输出 CRS `CRS84`；节点处理仍统一到 `EPSG:3857`。

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
  - 组内所有 node 均落入或接触 `DriveZone`，代表 node `has_evd = yes`
  - 若个别组内 node 未严格命中，但到 `DriveZone` evidence 面距离不超过 `1.5m`，仍视为边界容差命中
  - 任一组内 node 既未严格命中、也超过 `1.5m` evidence 面容差时，代表 node `has_evd = no`
  - Step1 summary 必须记录 `params.has_evd_evidence_tolerance_m`
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
- 若启用 `rcsdnode_path`，且命中的 `RCSDIntersection` 面内没有可用 RCSDNode 语义路口：
  - 不将该命中视为可消费锚定
  - 代表 node `is_anchor = no`
  - relation evidence 写 `relation_state = rcsdintersection_no_rcsd_semantic_node / status_suggested = 1`
  - 不发布该 `RCSDIntersection` 到 `t07_rcsdintersection_anchor_surface.gpkg`
  - 后续由 T03/T04 虚拟路口聚合链路继续处理
- 单节点语义路口命中多个 `RCSDIntersection`：
  - `is_anchor = yes`
  - `anchor_reason = NULL`
  - 不输出 `node_error_1`
- `kind_2 = 64 / 128`：
  - `is_anchor = no`
  - `anchor_reason = NULL`
  - 不纳入 `fail1` 规则；若命中的同一个 `RCSDIntersection` 还对应其它 SWSD 语义路口，仍被 `fail2` 覆盖
- `kind_2 = 2048`：
  - 必须先执行 strict surface 判定：组内所有 SWSD node 必须被同一个 `RCSDIntersection` 面覆盖，且任一组内 node 不得被其它 `RCSDIntersection` 面覆盖。
  - 该 `RCSDIntersection` 面不得覆盖其它 SWSD 语义路口；这里的“其它”按 `mainnodeid` 语义路口判断，不只限 Step2 普通候选。
  - 启用 `rcsdnode_path` 后，该 `RCSDIntersection` 面必须覆盖且只覆盖一个 RCSD 语义路口；缺少 `RCSDNode` 上下文、覆盖 0 个或覆盖多个 RCSD 语义路口时均不得写成功锚定。
  - 满足以上条件时，Step2 写 `is_anchor = yes / anchor_reason = NULL`，relation evidence 写 `existing_rcsdintersection_matched / status_suggested = 0`，`base_id_candidate` 写唯一 RCSD 语义路口 id，并发布 Step2 surface。
  - 任一条件不满足时，Step2 写 `is_anchor = no / anchor_reason = NULL`，relation evidence 写独立拒绝原因；不纳入通用 `fail1 / fail2`，未被 Step3 可选兼容 relation 补锚的场景仍由 T03/T04 虚拟锚定。
- 对未命中上述豁免规则的多节点组，若同一组 node 命中两个及以上不同 `RCSDIntersection`：
  - `is_anchor = fail1`
  - `anchor_reason = NULL`
  - 输出 `node_error_1`
- 若一个 `RCSDIntersection` 面对应多个参与 Step2 的语义路口：
  - 先忽略代表 node `kind_2 = 1` 的组
  - 过滤后剩余组数大于 `1` 时，相关代表 node `is_anchor = fail2`
  - `fail2` 覆盖范围包括代表 node `kind_2 in {4, 8, 16, 64, 128}` 的语义路口
  - 输出 `node_error_2`
- 优先级：
  - `fail2 > fail1`
  - 被 `fail2` 覆盖时，`anchor_reason = NULL`

### 3.4 Step3 `intersection_match_all` 补锚

- Step3 必须独立运行，不与 Step1 / Step2 合并。
- Step3 surface 1V1 处理范围：
  - 代表 node `kind_2 in {4, 8, 16, 2048}`
- Step3 先处理 Step2 surface 1V1：
  - 读取 Step2 `t07_rcsdintersection_anchor_surface.gpkg`
  - 同一 SWSD 语义路口必须只对应一个 `RCSDIntersection` surface
  - 用该 surface 查询输入 `RCSDNode` 中被 surface 覆盖的 RCSD 语义路口
  - 若仅有一个 RCSD 语义路口，则建立 SWSD-RCSD 语义路口关系并输出到 `intersection_match_t07.geojson`
  - 若有多个 RCSD 语义路口，则不建立成功关系，输出 `RCSDNode_error.gpkg`
  - 若没有 RCSD 语义路口，则只写 audit / summary，不输出 `RCSDNode_error.gpkg`
- Step3 再处理兼容 relation 补充候选，候选 SWSD 语义路口必须同时满足：
  - 代表 node `kind_2 in {4, 8, 16, 128, 2048}`
  - 代表 node `has_evd = yes`
  - 代表 node `is_anchor = no`
- 对候选 SWSD 语义路口，在 `intersection_match_all.geojson` 中按 `target_id = SWSD 语义路口 id` 查找 relation。
- 只有 relation 同时满足 `status = 0` 且 `base_id != 0` 时，才视为成功关联 RCSD 语义路口。
- 成功 relation 的 `base_id` 必须能在输入 `RCSDNode.id/mainnodeid` 中找到，且没有被 Step2 surface 1V1 阶段关联；否则不得写锚定成功。
- 成功通过上述校验后：
  - 输出该 relation 到 `intersection_match_t07.geojson`
  - 将对应 SWSD 代表 node `is_anchor = yes`
  - 将对应 SWSD 代表 node `anchor_reason = NULL`
- `kind_2 = 64` 不进入 Step3，后续由专项规则处理。
- `kind_2 = 128` 不进入 Step3 surface 1V1 推导；`kind_2 = 2048` 仅在 Step2 strict surface 已发布时进入 Step3 surface 1V1 推导。`kind_2 = 128 / 2048` 均可作为兼容 relation 补充候选，成功后只写代表 node `is_anchor = yes / anchor_reason = NULL` 并输出 relation。
- Step3 不读取、生成或统计 Segment。

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
- `performance.elapsed_seconds`
- `performance.stage_timings`，至少区分读取、语义路口准备、业务处理、`nodes.gpkg` 写出与审计 / summary 写出。

### 4.2 Step2 输出

目录：

```text
<out_root>/<run_id>/step2_anchor_recognition/
```

文件：

- `nodes.gpkg`
- `node_error_1.gpkg/csv/json`
- `node_error_2.gpkg/csv/json`
- `t07_rcsdintersection_anchor_surface.gpkg`
- `t07_swsd_rcsd_relation_evidence.csv/json`
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
- `roundabout_reason_count`（当前固定为 `0`，保留字段兼容）
- `t_reason_count`
- `relation_evidence_row_count`
- `surface_candidate_count`
- `rcsdintersection_no_rcsdnode_count`
- `t_junction_surface_anchor_count`
- `t_junction_surface_rejected_count`
- `input_paths`
- `output_paths`
- `target_crs`
- `performance.elapsed_seconds`
- `performance.stage_timings`，至少区分读取、`RCSDIntersection` 空间索引、语义路口准备、候选判定、冲突处理、`nodes.gpkg` 写出、error 输出与审计 / summary 写出。

### 4.3 Step3 输出

目录：

```text
<out_root>/<run_id>/step3_intersection_match/
```

文件：

- `nodes.gpkg`
- `intersection_match_t07.geojson`
- `t07_rcsdintersection_anchor_surface.gpkg`
- `RCSDNode_error.gpkg`
- `t07_swsd_rcsd_relation_evidence.csv/json`
- `relation_cardinality_errors.csv/json`
- `t07_step3_summary.json`
- `t07_step3_audit.csv/json`
- `t07_step3_perf.json`

Step3 summary 至少记录：

- `semantic_junction_count`
- `step3_scope_kind2_count`
- `candidate_count`
- `accepted_count`
- `not_candidate_count`
- `skipped_kind2_count`
- `relation_missing_count`
- `relation_failure_count`
- `relation_duplicate_count`
- `rcsd_missing_count`
- `step2_surface_1v1_relation_count`
- `intersection_match_backfill_relation_count`
- `step2_surface_no_rcsd_count`
- `rcsdnode_error_surface_count`
- `rcsdnode_error_count`
- `already_linked_base_skip_count`
- `swsd_multi_rcsd_error_count`
- `representative_missing_count`
- `relation_evidence_row_count`
- `step2_anchor_count`
- `step3_anchor_count`
- `total_anchor_count`
- `relation_cardinality_error_count`
- `one_target_to_many_base_count`
- `many_target_to_one_base_count`
- `duplicate_target_rows_count`
- `relation_cardinality_passed`
- `input_paths`
- `output_paths`
- `crs.process`
- `crs.intersection_match_t07`
- `performance.elapsed_seconds`
- `performance.stage_timings`，至少区分读取、索引准备、候选判定、输出写出与审计 / summary 写出。
- `output_strategy.nodes_write_mode` 与 `output_strategy.relation_write_mode`，用于确认是否命中 Step3 快路径。
- `output_strategy.anchor_surface_write_mode`，用于确认 Step3 surface 是复制 Step2 结果还是空输出。

## 5. EntryPoints

T07 当前不新增 repo 官方 CLI。稳定执行面为模块内 callable runner，并由已登记的内网脚本包装。

Callable runner：

```python
from rcsd_topo_poc.modules.t07_semantic_junction_anchor import (
    run_t07_step1_has_evd,
    run_t07_step2_anchor_recognition,
    run_t07_semantic_junction_anchor,
    run_t07_step3_intersection_match,
)
```

内网脚本：

```bash
scripts/t07_run_semantic_junction_anchor_innernet.sh
scripts/t07_run_step3_intersection_match_innernet.sh
```

说明：

- 脚本默认读取内网 `nodes / DriveZone / RCSDIntersection` 路径，可通过 `NODES_PATH / DRIVEZONE_PATH / INTERSECTION_PATH` 覆盖。
- 脚本可通过 `NODES_LAYER / DRIVEZONE_LAYER / INTERSECTION_LAYER` 与 `NODES_CRS / DRIVEZONE_CRS / INTERSECTION_CRS` 覆盖图层名和 CRS。
- 脚本不接受 `SEGMENT_PATH`，不读取、不生成、不统计 Segment。
- Step3 脚本为历史兼容保留自动发现与默认路径能力；正式运行必须通过 `NODES_PATH / INTERSECTION_MATCH_ALL_PATH / RCSDNODE_PATH` 显式指定输入。T10 全量总控不得依赖 Step3 脚本默认 relation 路径。
- 若后续要新增 repo CLI、其它 repo 级脚本、`tools/`、模块 `run.py` 或模块 `__main__.py`，必须另行获得用户授权，并同步 `docs/repository-metadata/entrypoint-registry.md`。

## 5.1 Performance

- T07 GPKG 输出复用 T08 的直接 SQLite GeoPackage 写出路径，避免 Fiona 逐要素 sink 写出。
- `nodes.gpkg / node_error_1.gpkg / node_error_2.gpkg` 均按 copy-on-write 输出，不修改输入。
- Step2 `t07_rcsdintersection_anchor_surface.gpkg` 发布 Step2 后 `is_anchor = yes` 且可定位 `RCSDIntersection` 的 accepted surface candidate；严格通过的 `kind_2 = 2048` 也按唯一 RCSD 语义路口 id 写 `base_id_candidate`。`fail1` 多 RCSDIntersection 场景可发布 `review_required` surface candidate 供下游追溯。`t07_swsd_rcsd_relation_evidence.csv/json` 采用 T02 relation evidence 字段族。
- Step3 `nodes.gpkg` 继续按 copy-on-write 输出，不修改 Step2 输入；`t07_rcsdintersection_anchor_surface.gpkg` 复制 Step2 同名结果；`intersection_match_t07.geojson` 包含 Step2 surface 1V1 推导关系与兼容 relation 补充关系；Step3 `t07_swsd_rcsd_relation_evidence.csv/json` 以 Step2 evidence 为基础，用 Step3 成功 relation 覆盖同 `target_id` 行，并输出 Step2 / Step3 锚定计数。
- Step3 对最终候选成功 relation 执行 T05 同口径基数质检；若存在同一 `target_id` 挂接多个 `base_id`、多个 `target_id` 挂接同一 `base_id` 或重复 success target，输出 `relation_cardinality_errors.csv/json`。其中 `one_target_to_many_base` 的 SWSD 语义路口必须从 `intersection_match_t07.geojson` 移除，并将代表 node 回写为 `is_anchor = no / anchor_reason = NULL`。
- Step3 在输入 `nodes.gpkg` 已为 `EPSG:3857` GeoPackage 时，优先复制输入 GPKG 并用 SQLite 只更新命中的代表 node，避免全量重写节点几何；copy-update 输出必须补齐 `gpkg_ogr_contents` 与增删触发器，避免 QGIS 旧版 OGR provider filter 后显示全量计数。
- Step3 在 `intersection_match_all.geojson` 为 `CRS84` 时，优先按原始 GeoJSON relation 写出 `intersection_match_t07.geojson`，避免无业务必要的几何投影。
- perf JSON 必须记录 `stage_timings`，用于定位 full-input 下的读取、空间索引、业务处理与写出耗时。

## 5.2 2026-06-14 补充规则：fail1 多 RCSDIntersection handoff

- Step2 对多节点 SWSD 语义路口命中多个 RCSDIntersection 的场景仍保留 `is_anchor = fail1`、`anchor_reason = NULL` 与 `node_error_1` 审计。
- 当该 fail1 场景存在明确的 RCSDIntersection `id`，且该 `id` 可作为下游 RCSD 语义节点 base 候选时，`t07_swsd_rcsd_relation_evidence.csv/json` 必须输出 `relation_state = multiple_intersections_for_group`、`status_suggested = 1`，并在 `base_id_candidate` 中写入全部非零 base id。
- 同一场景下，`t07_rcsdintersection_anchor_surface.gpkg` 可以发布这些 RCSDIntersection surface candidate，供 T05 Phase1 形成可追溯 surface 上下文；这不改变代表 node 的 `is_anchor = fail1` 审计事实。
- `fail2` 仍优先于 `fail1`，不适用本 handoff 规则。

## 6. Params

- `run_id`：可选运行 ID；为空时自动生成。
- `nodes_layer / drivezone_layer / intersection_layer / rcsdnode_layer`：可选图层名。
- `nodes_crs / drivezone_crs / intersection_crs / intersection_match_all_crs / rcsdnode_crs`：可选 CRS override。

## 7. Acceptance

1. Step1 可在无 Segment 输入下独立计算语义路口级 `has_evd`。
2. Step2 可在无 Segment 输入下独立计算语义路口级 `is_anchor / anchor_reason`。
3. `kind_2` 仅使用代表 node 字段，且仅处理 `{4, 8, 16, 64, 128, 2048}`。
4. 非处理范围 `kind_2` 的 `has_evd / is_anchor / anchor_reason` 均为 `NULL`。
5. 从属 node 不写业务状态。
6. `kind_2 = 64 / 128` 在 Step2 基础判定写 `no / NULL`，但一面多 SWSD 语义路口时必须被 `fail2` 覆盖。
7. `kind_2 = 2048` 只有在 strict single-surface / single-SWSD / single-RCSD 条件全部满足时才可建立 Step2 surface 成功关系；不满足时写 `no / NULL`，不得参与或接收通用 `fail2`；Step3 可在兼容成功 relation 可验证时补写 T07 relation anchor。
8. `fail2` 优先于 `fail1`。
9. Step3 的 Step2 surface 1V1 处理范围为 `kind_2 in {4, 8, 16, 2048}`；兼容 relation 补充候选范围为 `kind_2 in {4, 8, 16, 128, 2048}`，且必须满足 `has_evd = yes`、`is_anchor = no`。
10. Step2 必须输出 `t07_rcsdintersection_anchor_surface.gpkg` 与 `t07_swsd_rcsd_relation_evidence.csv/json`。
11. Step3 仅在 Step2 surface 1V1 推导成功，或兼容 relation 成功且 RCSD `base_id` 存在并未被前段占用时，写 `is_anchor = yes` 并输出 `intersection_match_t07.geojson`。
12. Step3 必须输出复制 Step2 结果的 `t07_rcsdintersection_anchor_surface.gpkg`，以及合并 Step2 与 Step3 成功补锚成果的 `t07_swsd_rcsd_relation_evidence.csv/json`。
13. Step3 必须输出 `RCSDNode_error.gpkg`，记录 Step2 surface 面内包含多个 RCSD 语义路口的错误。
14. Step3 必须输出 `relation_cardinality_errors.csv/json`，记录候选成功 relation 中的 1:N、N:1 与重复 success target；若出现 SWSD 1:N，必须取消该 SWSD 已建立关系并回写 `is_anchor = no`。
15. 所有 CRS、字段、几何、代表 node 缺失问题都有明确审计。
16. 输出不包含 Segment 工件或 Segment 视角 summary。
