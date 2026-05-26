# T06 - INTERFACE_CONTRACT

## 定位

本文件是 `t06_segment_fusion_precheck` 的稳定接口契约。T06 当前只覆盖 Segment 替换前置检查：

- Step1：识别可参与融合的 SWSD Segment 单元。
- Step2：基于 relation 与 buffer-based 策略构建 RCSDSegment 审查成果；兼容 `candidates / replaceable` 输出由 buffer 成功结果派生。

本模块不执行 Segment 替换，不重塑路口，不修改 T01 / T05 输出。

## 1. 目标与范围

### 1.1 当前正式支持

- 消费 T01 `segment.gpkg` 与 final `nodes.gpkg`。
- 按 `pair_nodes + junc_nodes` 的语义路口 ID 集合判断 Segment 是否具备 EVD 与 anchor/fallback 基础。
- 对 `junc_nodes` 启用 `kind_2 in {1,4096,8192}` 豁免：命中 junc node 不参与 Step1 `has_evd / is_anchor` 判定，也不作为 Step2 T05 relation 必检映射节点；该豁免不适用于 `pair_nodes`。
- 将 `is_anchor = fail4_fallback` 视为可融合 anchor。
- 消费 T05 Phase 2 `intersection_match_all.geojson`、`rcsdroad_out.gpkg`、`rcsdnode_out.gpkg`。
- 基于 SWSD Segment 50m buffer、RCSDRoad `intersects + 阈值`、RCSDNode `covers/within` 生成 buffer-based RCSDSegment 审查成果，作为 Step2 唯一正式构建策略。
- 构建 buffer 候选连通图前，使用 `formway` bit7/128 排除提前右转 road；不得通过几何形态反推提前右转。
- 不再执行 pair-to-pair BFS 路径搜索、SWSD 单向方向推导、RCSD 方向一致性、主轴 / 粗长度趋势或唯一性筛选。

### 1.2 当前非目标

- 不执行 SWSD Segment 替换。
- 不重塑路口。
- 不修改 T01 主链、T05 主链或任何输入成果。
- 不新增 repo CLI、`tools`、`Makefile`、模块 `run.py` 或模块 `__main__.py`。
- 除 `scripts/t06_run_innernet_precheck.py` 这个内网运行包装外，不新增其它 repo 级脚本入口。
- 不使用精细几何拟合指标作为核心硬门槛。

## 2. Inputs

### 2.1 Step1 Runner

```python
run_t06_step1_identify_fusion_units(
    *,
    swsd_segment_path,
    swsd_nodes_path,
    out_root,
    run_id=None,
    progress=False,
)
```

必选输入：

- `swsd_segment_path`：T01 `segment.gpkg`，依赖字段 `id / sgrade / pair_nodes / junc_nodes / roads / geometry`。
- `swsd_nodes_path`：final `nodes.gpkg`，依赖字段 `id / mainnodeid / has_evd / is_anchor / kind_2`。
- `out_root`：输出根目录。

### 2.2 Step2 Runner

```python
run_t06_step2_extract_rcsd_segments(
    *,
    swsd_fusion_units_path,
    swsd_segment_path,
    swsd_roads_path,
    swsd_nodes_path,
    intersection_match_path,
    rcsdroad_path,
    rcsdnode_path,
    out_root,
    run_id=None,
    max_main_axis_angle_diff_deg=60.0,
    min_coarse_length_ratio=0.4,
    max_coarse_length_ratio=2.5,
    buffer_distance_m=50.0,
    min_buffer_road_overlap_ratio=0.2,
    min_buffer_road_overlap_length_m=1.0,
    advance_right_formway_bit=128,
    progress=False,
)
```

必选输入：

- `swsd_fusion_units_path`：Step1 输出 `t06_swsd_segment_fusion_units.gpkg`。
- `swsd_segment_path`：T01 `segment.gpkg`。
- `swsd_roads_path`：SWSD road body；Step2 保留该参数以兼容内网端到端脚本输入形态，buffer-based 主链不读取它做方向判断。
- `swsd_nodes_path`：final `nodes.gpkg`；Step2 保留该参数以兼容内网端到端脚本输入形态，buffer-based 主链不读取它做方向判断。
- `intersection_match_path`：T05 Phase 2 `intersection_match_all.geojson`。
- `rcsdroad_path`：T05 Phase 2 `rcsdroad_out.gpkg`。
- `rcsdnode_path`：T05 Phase 2 `rcsdnode_out.gpkg`，依赖字段 `id / mainnodeid / subnodeid` 用于把 RCSDRoad raw endpoint 归一到 RCSD 语义主节点。
- `out_root`：输出根目录。

### 2.3 关键输入语义

- `pair_nodes + junc_nodes` 按语义路口 ID 判定，不按物理 node 展开作为主判断。
- Step1 解析 final `nodes.gpkg` 时，语义节点属性优先使用 `id` 精确匹配记录；只有不存在对应 `id` 记录时，才使用 `mainnodeid` 命中的组内记录作为 fallback。
- `kind_2 in {1,4096,8192}` 只对 `junc_nodes` 生效：命中 junc node 从 Step1 `has_evd / is_anchor` eligibility 检查集合与 Step2 T05 relation 必检映射集合中移除，但仍保留在 `junc_nodes / semantic_node_set` 输出中；`pair_nodes` 命中这些 `kind_2` 也不豁免。
- `intersection_match_all.geojson` 中只有 `status = 0` 且 `base_id > 0` 的 relation 可用。
- `base_id` 必须是 RCSD 语义路口主 node id。
- Step2 构建 buffer candidate graph 时，必须先按 `rcsdnode_path` 的 `mainnodeid / subnodeid` 做语义节点归一化：`id` 若有有效 `mainnodeid` 则归一到 `mainnodeid`，`subnodeid` 列表中的物理节点也归一到所属 `mainnodeid`；relation required nodes 与 RCSDRoad `snodeid / enodeid` 必须使用同一 canonical key 判定连通。
- `direction` 当前不参与 buffer-based Step2 硬规则；RCSDRoad 连通按无向关系构建，方向字段仅作为输入原始属性保留。
- `junc_nodes` 在 RCSD 抽取中是内部通过 + 侧向阻断，不是 hard-stop；retained RCSD graph 的叶子端点只能是 `pair_nodes` 对应的 RCSD semantic nodes。
- buffer-based RCSDSegment 审查中，required semantic nodes 为 `pair_nodes` relation 与非豁免 `junc_nodes` relation；`junc_kind2_exempt_nodes` 若有 relation，仅作为 optional allowed semantic nodes 审计保留。
- 额外 T05 mapped semantic nodes 必须按 seed-based pruning 判定为 `inner_nodes / out_nodes`；仅保留 `inner_nodes` 与 required / optional allowed 之间的连通 RCSDRoad。
- `formway` 为 bit mask；提前右转必须按 `formway & 128 != 0` 判断，不得写成 `formway == 128`。

## 3. Outputs

### 3.1 Step1 输出

目录：

```text
<out_root>/<run_id>/step1_identify_fusion_units/
```

文件：

- `t06_swsd_segment_evd_candidates.gpkg/csv/json`
- `t06_swsd_segment_candidates.gpkg/csv/json`
- `t06_swsd_segment_fusion_units.gpkg/csv/json`
- `t06_swsd_segment_final_fusion_units.gpkg/csv/json`
- `t06_swsd_segment_rejected.gpkg/csv/json`
- `t06_step1_summary.json`

`t06_swsd_segment_candidates` 为通过 EVD 基础检查后的 SWSD Segment 候选集；`t06_swsd_segment_final_fusion_units` 为通过 anchor / fallback 检查后的 SWSD Segment 最终可融合集合。`t06_swsd_segment_evd_candidates` 与 `t06_swsd_segment_fusion_units` 保留为兼容输出。

`candidates / final_fusion_units / fusion_units` 稳定字段：

- `swsd_segment_id`
- `sgrade`
- `pair_nodes`
- `junc_nodes`
- `semantic_node_set`
- `roads`
- `pair_node_count`
- `junc_node_count`
- `junc_kind2_exempt_nodes`
- `has_fail4_fallback`
- `geometry`

`rejected` 稳定字段：

- `swsd_segment_id`
- `reject_stage`
- `reject_reason`
- `failed_node_ids`
- `failed_node_attrs`
- `junc_kind2_exempt_nodes`
- `pair_nodes`
- `junc_nodes`
- `sgrade`
- `geometry`

### 3.2 Step2 输出

目录：

```text
<out_root>/<run_id>/step2_extract_rcsd_segments/
```

文件：

- `t06_rcsd_segment_candidates.gpkg/csv/json`
- `t06_rcsd_segment_replaceable.gpkg/csv/json`
- `t06_rcsd_segment_rejected.gpkg/csv/json`
- `t06_rcsd_buffer_segments.gpkg/csv/json`
- `t06_rcsd_buffer_segment_rejected.gpkg/csv/json`
- `t06_step2_summary.json`

### 3.3 文本证据包 helper 输出

T06 文本证据包 helper 不是新的业务阶段，也不登记为 repo 官方 CLI；它用于内外网结果回传、轻量审计取证与可复跑信息归档。

默认打包文件：

- `<run_root>/t06_segment_fusion_precheck_evidence_bundle.txt`
- `<run_root>/t06_segment_fusion_precheck_evidence_bundle_size_report.json`

文本证据包默认按 T01 输入证据包模式自动分片，单个 `.txt` 分片不得超过 `250KB`；可通过 `--max-text-size-bytes` 覆盖。第一片使用默认输出名或用户指定的 `--out-txt`，第二片起按 `<stem>.part_0002_of_000N.txt` 命名。解包 helper 接受任意一个分片路径，必须自动读取同目录其它分片并校验完整 payload SHA256。

包内稳定结构：

- `t06_evidence_manifest.json`
  - 记录 bundle 版本、source run root、输入清单、Step1 / Step2 summary、输出文件审计、checksum 与编码信息。
- `t06_evidence_size_report.json`
  - 记录 bundle 文本体量、压缩 payload 体量、逐文件 raw / compressed size、缺失的可选输出文件、`limit_bytes / within_limit / split_bundle` 分片审计信息。
- `audit/t06_input_manifest.json`
  - 记录与 `scripts/t06_run_innernet_precheck.py` 同形的输入参数、解析后的六个输入文件路径、运行参数、文件大小、SHA256 与 mtime。
- `audit/replay_t06_run_innernet_precheck.sh`
  - 记录使用同一输入参数复跑 T06 的命令。
- `run/<step_dir>/...`
  - 默认包含 Step1 / Step2 summary、JSON / CSV 审计输出。
  - 显式传入 `--include-output-vectors` 时额外包含 Step1 / Step2 GPKG 输出。
- `inputs/...`
  - 仅显式传入 `--include-input-files` 时写入六个原始输入文件副本。

输入切片包使用同一文本容器，但 selection 为 `t06-input-centered-spatial-slice`。稳定结构：

- `slice/swsd/segment.geojson`
- `slice/swsd/roads.geojson`
- `slice/swsd/nodes.geojson`
- `slice/t05_phase2/intersection_match_all.geojson`
- `slice/t05_phase2/rcsdroad_out.geojson`
- `slice/t05_phase2/rcsdnode_out.geojson`
- `slice/t06_input_slice_summary.json`

输入切片选择参数：

- `center_x / center_y`：EPSG:3857 中心点坐标。
- `profile_id`：默认 `XS`，支持 `XXXS / XXS / XS / S / M`。
- `radius_m`：可选；显式提供时覆盖 profile 半径。

默认 profile 半径：

- `XXXS = 250m`
- `XXS = 500m`
- `XS = 1000m`
- `S = 2000m`
- `M = 5000m`

输入切片选择规则：

- 用中心点与半径构建 EPSG:3857 方形窗口。
- 选中与窗口相交的 SWSD Segment。
- 根据选中 Segment 的 `roads / pair_nodes / junc_nodes` 补齐必要 SWSD roads / nodes。
- 同时保留窗口内上下文 SWSD roads / nodes。
- 保留选中语义节点相关 T05 relation，并按有效 relation 补齐 mapped RCSD semantic nodes。
- 保留窗口内 RCSDRoad / RCSDNode，以及连接 selected RCSD node 的 RCSDRoad。

`candidates` 稳定字段：

- `swsd_segment_id`
- `rcsd_candidate_id`
- `candidate_strategy`
- `candidate_status`
- `candidate_reason`
- `swsd_sgrade`
- `swsd_directionality`
- `swsd_pair_nodes`
- `rcsd_pair_nodes`
- `swsd_junc_nodes`
- `junc_kind2_exempt_nodes`
- `rcsd_junc_nodes`
- `required_rcsd_nodes`
- `optional_allowed_rcsd_nodes`
- `candidate_rcsd_road_ids`
- `candidate_rcsd_node_ids`
- `retained_rcsd_road_ids`
- `retained_node_ids`
- `inner_node_ids`
- `out_node_ids`
- `unexpected_endpoint_node_ids`
- `excluded_advance_right_turn_road_ids`
- `selected_component_id`
- `candidate_road_count`
- `retained_road_count`
- `candidate_node_count`
- `retained_node_count`
- `geometry`

`candidates` 与 `replaceable` 为兼容输出，均由 buffer 成功结果派生；`replaceable.rcsd_road_ids` 等于 buffer 裁剪后的 `retained_rcsd_road_ids`。`rejected` 输出保留 `failed_pair_nodes / failed_junc_nodes / junc_kind2_exempt_nodes`，用于定位 relation 必检集合与豁免集合，同时记录 buffer 构建失败 reason。

`t06_rcsd_buffer_segments` 稳定字段：

- `swsd_segment_id`
- `buffer_candidate_id`
- `buffer_status`
- `buffer_reason`
- `required_rcsd_nodes`
- `optional_allowed_rcsd_nodes`
- `retained_rcsd_road_ids`
- `candidate_rcsd_road_ids`
- `candidate_rcsd_node_ids`
- `excluded_advance_right_turn_road_ids`
- `retained_node_ids`
- `inner_node_ids`
- `out_node_ids`
- `unexpected_endpoint_node_ids`
- `selected_component_id`
- `candidate_road_count`
- `retained_road_count`
- `candidate_node_count`
- `retained_node_count`
- `geometry`

`t06_rcsd_buffer_segment_rejected` 稳定字段：

- `swsd_segment_id`
- `reject_stage`
- `reject_reason`
- `required_rcsd_nodes`
- `optional_allowed_rcsd_nodes`
- `missing_required_node_ids`
- `retained_rcsd_road_ids`
- `candidate_rcsd_road_ids`
- `candidate_rcsd_node_ids`
- `excluded_advance_right_turn_road_ids`
- `retained_node_ids`
- `inner_node_ids`
- `out_node_ids`
- `unexpected_endpoint_node_ids`
- `selected_component_id`
- `candidate_road_count`
- `retained_road_count`
- `candidate_node_count`
- `retained_node_count`

## 4. EntryPoints

T06 当前不新增 repo CLI。稳定执行面包括模块内 callable runner 与一个已登记的内网运行包装脚本。

```python
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import (
    run_t06_step1_identify_fusion_units,
    run_t06_step2_extract_rcsd_segments,
)
```

内网脚本入口：

```bash
.venv/bin/python scripts/t06_run_innernet_precheck.py \
  --swsd-segment /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.gpkg \
  --swsd-roads /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/roads.gpkg \
  --swsd-nodes /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T04/nodes.gpkg \
  --t05-phase2-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment/t05_phase2_innernet \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck
```

脚本默认从 `--t05-phase2-root` 自动发现 `intersection_match_all.geojson`、`rcsdroad_out.gpkg` 与 `rcsdnode_out.gpkg`；三者也可以通过显式参数覆盖。

文本证据包 helper 仅作为模块内非官方 helper 调用，不新增 repo CLI / scripts 入口。打包参数保持与内网端到端脚本一致：

```bash
.venv/bin/python -c "import sys; from rcsd_topo_poc.modules.t06_segment_fusion_precheck.text_bundle import run_t06_export_text_bundle_from_args as run; raise SystemExit(run(sys.argv[1:]))" \
  --swsd-segment /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.gpkg \
  --swsd-roads /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/roads.gpkg \
  --swsd-nodes /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T04/nodes.gpkg \
  --t05-phase2-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment_active_road_fix_2/t05_phase2_full \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck \
  --run-id t06_innernet_precheck
```

输入切片包：

```bash
.venv/bin/python -c "import sys; from rcsd_topo_poc.modules.t06_segment_fusion_precheck.text_bundle import run_t06_export_input_text_bundle_from_args as run; raise SystemExit(run(sys.argv[1:]))" \
  --swsd-segment /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.gpkg \
  --swsd-roads /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/roads.gpkg \
  --swsd-nodes /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T04/nodes.gpkg \
  --t05-phase2-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment_active_road_fix_2/t05_phase2_full \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck \
  --run-id t06_innernet_precheck \
  --center-x <EPSG3857_X> \
  --center-y <EPSG3857_Y> \
  --profile-id XS
```

解包：

```bash
.venv/bin/python -c "import sys; from rcsd_topo_poc.modules.t06_segment_fusion_precheck.text_bundle import run_t06_decode_text_bundle_from_args as run; raise SystemExit(run(sys.argv[1:]))" \
  --bundle-txt /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck/t06_innernet_precheck/t06_segment_fusion_precheck_evidence_bundle.txt \
  --out-dir /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck/t06_innernet_precheck_decoded_bundle
```

## 5. Params

- `run_id`：可选运行 ID；为空时自动生成。
- `progress`：是否打印稀疏进度。
- `max_main_axis_angle_diff_deg`：兼容保留参数；buffer-based Step2 主链不再使用主轴趋势硬筛。
- `min_coarse_length_ratio`：兼容保留参数；buffer-based Step2 主链不再使用粗长度趋势硬筛。
- `max_coarse_length_ratio`：兼容保留参数；buffer-based Step2 主链不再使用粗长度趋势硬筛。
- `buffer_distance_m`：buffer-based RCSDSegment 审查缓冲距离，默认 `50.0`。
- `min_buffer_road_overlap_ratio`：RCSDRoad 与 buffer 相交长度占比阈值，默认 `0.2`。
- `min_buffer_road_overlap_length_m`：RCSDRoad 与 buffer 相交长度下限，默认 `1.0`。
- `advance_right_formway_bit`：提前右转 bit mask，默认 `128`。
- `max_text_size_bytes`：文本证据包单个 `.txt` 分片体量上限，默认 `250KB`；仅作用于文本包 helper，不影响 Step1 / Step2 业务运行。
- `rcsd_semantic_node_alias_count`：Step2 summary 审计字段，记录参与 `subnodeid/id -> mainnodeid` 归一化的非恒等 alias 数量。

## 6. Acceptance

1. Step1 runner 可独立运行并输出 SWSD Segment 候选集、最终可融合集合、兼容 EVD candidates / fusion units、rejected 与 summary。
2. Step2 runner 可独立运行并输出 buffer-based RCSDSegment 主成果、兼容 candidates、兼容 replaceable、rejected、buffer rejected 与 summary。
3. `fail4_fallback` 能进入 Step1 final fusion units，但 Step2 对 relation 必检集合仍必须校验 T05 relation。
4. `junc_nodes.kind_2 in {1,4096,8192}` 的节点不参与 Step1 `has_evd / is_anchor` 判定，也不进入 Step2 T05 relation 必检映射集合；同值 `pair_nodes` 仍按原规则判定并映射。
5. Step2 不执行 pair-to-pair BFS 路径搜索、SWSD 单向方向推导、RCSD 方向一致性、主轴 / 粗长度趋势或唯一性筛选。
6. `junc_nodes` 执行 required coverage、内部通过 + 侧向阻断；retained graph 中出现非 pair leaf endpoint 时必须拒绝并输出 `unexpected_endpoint_node_ids`。
7. 所有解析、映射、buffer 构建失败都有明确 reason。
8. 输入文件不被原地修改。
9. buffer-based RCSDSegment 审查必须按 `formway` bit7/128 排除提前右转 road，并在 summary / 输出中保留审计。
