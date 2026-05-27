# T06 Segment Fusion Precheck

`t06_segment_fusion_precheck` 是 SWSD-RCSD Segment 数据融合的前置模块。当前只做 Step1 / Step2，不执行替换。

## 当前范围

- Step1：从 T01 `segment.gpkg` 中识别可参与融合的 SWSD Segment。
- Step2：基于 T05 Phase 2 relation 与 copy-on-write RCSD 网络，仅使用 buffer-based 策略构建 RCSDSegment 审查成果；兼容输出 `candidates / replaceable` 由 buffer 成功结果派生。

## 非目标

- 不执行 Segment 替换。
- 不重塑路口。
- 不修改 T01 / T05 输出。
- 不新增 repo CLI。
- 仅保留一个内网运行包装脚本：`scripts/t06_run_innernet_precheck.py`。

## Callable Runner

```python
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import (
    run_t06_segment_fusion_precheck,
)

artifacts = run_t06_segment_fusion_precheck(
    swsd_segment_path="segment.gpkg",
    swsd_roads_path="roads.gpkg",
    swsd_nodes_path="nodes.gpkg",
    intersection_match_path="intersection_match_all.geojson",
    rcsdroad_path="rcsdroad_out.gpkg",
    rcsdnode_path="rcsdnode_out.gpkg",
    out_root="outputs/_work/t06_segment_fusion_precheck",
    run_id="manual_run",
)
```

## 内网脚本

```bash
.venv/bin/python scripts/t06_run_innernet_precheck.py \
  --swsd-segment /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.gpkg \
  --swsd-roads /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/roads.gpkg \
  --swsd-nodes /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T04/nodes.gpkg \
  --t05-phase2-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment/t05_phase2_innernet \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck
```

脚本会运行 Step1 + Step2，并在 stdout 打印包含输入路径、输出路径与核心计数的 JSON 摘要。

## 文本证据包 helper（非官方 CLI）

文本证据包 helper 用于内外网之间回传 T06 运行审计结果，不登记为 repo 官方 CLI。默认 compact 包包含 Step1 / Step2 的 summary、JSON / CSV 审计输出、完整输入路径 / 参数 / 文件大小 / SHA256 清单与可复跑命令；默认不带大体量 GPKG 输出，也不带六个原始输入文件。需要输出向量时显式加 `--include-output-vectors`，需要完整输入复现包时显式加 `--include-input-files`。

helper 默认按 T01 输入证据包模式自动分片，单个 `.txt` 分片不超过 `250KB`。主文件仍为 `t06_segment_fusion_precheck_evidence_bundle.txt` 或输入切片包指定的 `--out-txt`，后续分片命名为 `<stem>.part_0002_of_000N.txt`。可用 `--max-text-size-bytes` 覆盖上限；解包时传任意一个分片路径即可自动读取同目录其它分片并校验完整 payload。

打包参数保持与内网端到端脚本一致，`--t05-phase2-root` 会自动解析 `intersection_match_all.geojson / rcsdroad_out.gpkg / rcsdnode_out.gpkg`：

```bash
.venv/bin/python -c "import sys; from rcsd_topo_poc.modules.t06_segment_fusion_precheck.text_bundle import run_t06_export_text_bundle_from_args as run; raise SystemExit(run(sys.argv[1:]))" \
  --swsd-segment /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.gpkg \
  --swsd-roads /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/roads.gpkg \
  --swsd-nodes /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T04/nodes.gpkg \
  --t05-phase2-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment_active_road_fix_2/t05_phase2_full \
  --out-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck \
  --run-id t06_innernet_precheck
```

解包：

```bash
.venv/bin/python -c "import sys; from rcsd_topo_poc.modules.t06_segment_fusion_precheck.text_bundle import run_t06_decode_text_bundle_from_args as run; raise SystemExit(run(sys.argv[1:]))" \
  --bundle-txt /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck/t06_innernet_precheck/t06_segment_fusion_precheck_evidence_bundle.txt \
  --out-dir /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck/t06_innernet_precheck_decoded_bundle
```

解包目录中 `audit/t06_input_manifest.json` 记录完整输入路径、参数、文件大小与 SHA256，`audit/replay_t06_run_innernet_precheck.sh` 记录可复跑命令，`run/` 下保留 T06 输出相对结构。`t06_evidence_size_report.json` 会记录 `limit_bytes`、`within_limit` 与 `split_bundle`，用于确认分片数量和每片大小。

### 输入切片包

输入切片包用于按中心点和范围标准抽取局部 SWSD / RCSD / relation 数据。切片选择逻辑：

- 用 `center_x / center_y / radius_m` 构建 EPSG:3857 方形窗口。
- 选中与窗口相交的 SWSD Segment。
- 根据选中 Segment 的 `roads / pair_nodes / junc_nodes` 补齐必要 SWSD roads / nodes。
- 保留窗口内上下文 SWSD roads / nodes。
- 保留相关 T05 relation，并按 relation 补齐 mapped RCSD semantic nodes。
- 保留窗口内 RCSDRoad / RCSDNode，以及连接 selected RCSD node 的 RCSDRoad。

默认范围标准：

- `XXXS = 250m`
- `XXS = 500m`
- `XS = 1000m`
- `S = 2000m`
- `M = 5000m`

可用 `--radius-m` 显式覆盖 profile 半径。

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

解包后 `slice/` 下包含 `swsd/segment.geojson`、`swsd/roads.geojson`、`swsd/nodes.geojson`、`t05_phase2/intersection_match_all.geojson`、`t05_phase2/rcsdroad_out.geojson`、`t05_phase2/rcsdnode_out.geojson` 与 `t06_input_slice_summary.json`。

## 关键规则

- `pair_nodes + junc_nodes` 按语义路口 ID 判定。
- `junc_nodes.kind_2 in {1,4096,8192}` 的节点不参与 Step1 `has_evd / is_anchor` 判定，也不进入 Step2 T05 relation 必检映射集合；`pair_nodes` 不适用该豁免。
- `is_anchor = fail4_fallback` 视为可融合 anchor。
- Step2 relation 只接受 `status = 0` 且 `base_id > 0`；必检集合为 `pair_nodes + 非豁免 junc_nodes`。
- Step2 RCSD 建图使用 `rcsdnode_out` 的 `mainnodeid / subnodeid` 做语义节点归一化，relation required nodes 与 RCSDRoad `snodeid / enodeid` 使用同一 canonical key 判定连通。
- Step2 把 `rcsdnode_out` 中按有效 `mainnodeid` 聚合出的全局 RCSD 语义路口组作为图边界与审计对象；组内所有 node 关联 road 均视为该语义路口的进入 / 退出道路，未映射到当前 Segment 的全局 RCSD 语义路口不能被当成普通通过节点，必须参与 seed pruning。
- Step2 buffer 审查以 SWSD Segment 50m buffer 筛选 RCSD 候选，RCSDRoad 使用 `intersects + 阈值`，并在构图前按 `formway` bit7/128 识别提前右转 road；提前右转 road 若两端均与非提前右转候选 road 形成二度链接则保留，否则排除。
- Step2 不把 buffer 候选连通分量直接作为 RCSDSegment；必须先基于 required semantic nodes 构建最小 corridor 子图，再输出 retained roads。
- Step2 双向 Segment 的 corridor 路径选择会惩罚明显短于 SWSD Segment 的 required-to-required connector，避免用路口内短连接替代完整反向 road。
- Step2 识别 RCSDRoad `formway & 1024 != 0` 为调头口；当调头 road 两端均属于 retained corridor node 时，作为内部调头 road 保留。
- Step2 buffer 裁剪对额外 T05 mapped semantic nodes 执行 seed-based pruning：处于 required corridor 内部的 seed 归为 `inner_nodes` 并可保留审计；触达孤立挂接或其它 out leaf 且不在 required corridor 内的 seed 归为 `out_nodes` 并剔除；retained graph 中若仍存在非 inner 的额外 mapped semantic node，则以 `unexpected_mapped_semantic_nodes` 拒绝。
- 双向 SWSD 的 pruning 保护范围包含 pair 两端正反向 directed corridor，避免提前裁掉另一侧 RCSD 主线。
- `swsd_directionality=dual` 的 retained RCSD graph 必须 pair 两端双向可达，否则以 `rcsd_not_bidirectional_for_swsd_dual` 拒绝。
- `swsd_directionality=single` 必须构建一条覆盖全部 required semantic nodes 的 pair 端到另一端有向 corridor，不得把无向 corridor 与有向 pair path 做并集；不满足时以 `rcsd_directed_path_missing` 拒绝。
- `junc_nodes` 是内部通过 + 侧向阻断，不是 hard-stop。
- Step2 retained RCSD graph 的叶子端点只能是 `pair_nodes` 对应的 RCSD semantic nodes；`junc_nodes` 或其它节点成为 retained leaf endpoint 时以 `unexpected_retained_endpoint_nodes` 拒绝。
- Step2 不再执行 pair-to-pair BFS 路径搜索、SWSD 单向方向推导、主轴趋势、长度趋势或唯一性筛选；`replaceable_count` 等于通过 buffer 构建与硬审计的结果数。

## 输出

Step1 输出：

- `t06_swsd_segment_evd_candidates.gpkg/csv/json`
- `t06_swsd_segment_candidates.gpkg/csv/json`
- `t06_swsd_segment_fusion_units.gpkg/csv/json`
- `t06_swsd_segment_final_fusion_units.gpkg/csv/json`
- `t06_swsd_segment_rejected.gpkg/csv/json`
- `t06_step1_summary.json`

其中 `t06_swsd_segment_candidates` 是通过 EVD 基础检查后的 SWSD Segment 候选集；`t06_swsd_segment_final_fusion_units` 是通过 anchor / fallback 检查后的 SWSD Segment 最终可融合集合。`evd_candidates` 与 `fusion_units` 继续保留为兼容输出。

Step2 输出：

- `t06_rcsd_segment_candidates.gpkg/csv/json`
- `t06_rcsd_segment_replaceable.gpkg/csv/json`
- `t06_rcsd_segment_rejected.gpkg/csv/json`
- `t06_rcsd_buffer_segments.gpkg/csv/json`
- `t06_rcsd_buffer_segment_rejected.gpkg/csv/json`
- `t06_step2_summary.json`

其中 `t06_rcsd_buffer_segments` 是正式主成果；`t06_rcsd_segment_candidates` 与 `t06_rcsd_segment_replaceable` 为兼容输出，内容由同一 buffer 成功结果派生，不再表示 BFS 路径候选。
