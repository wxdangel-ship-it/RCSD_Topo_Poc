# T06 Segment Fusion Precheck

`t06_segment_fusion_precheck` 是 SWSD-RCSD Segment 数据融合模块。当前 Step1 / Step2 / Step3 已实现。

## 当前范围

- Step1：从 T01 `segment.gpkg` 中识别可参与融合的 SWSD Segment。
- Step2：基于 T05 Phase 2 relation 与 copy-on-write RCSD 网络，仅使用 buffer-based 策略构建 RCSDSegment 候选，并在特殊路口组门控后输出最终 `replaceable` 集合。
- Step3：消费 Step2 可替换 RCSDSegment，按 Segment 单元输出融合后的 F-RCSD Road / Node，并重建涉及的语义路口关系。

## 非目标

- 不修改 T01 / T05 输出。
- 不新增 repo CLI。
- 仅保留已登记的 T06 repo 级脚本：`scripts/t06_run_innernet_precheck.py` 与 `scripts/t06_run_step3_segment_replacement.py`。
- Step3 不处理 Step2 rejected Segment，不通过几何猜测补救未通过 Step2 的 Segment。

## Step3 状态

Step3 任务书位于 `specs/t06-step3-segment-replacement/`。当前已确认的业务口径：

- 只消费 Step2 replaceable 成果。
- 删除被替换 SWSD Segment 涉及的 SWSDRoad。
- SWSDNode 只删除被替换 SWSDRoad 的端点 Node，不删除整个 SWSD 语义路口组。
- 引入 Step2 retained RCSDSegment 中的 RCSDRoad / RCSDNode。
- Step2 特殊路口组门控通过时，Step3 消费同目录 `t06_special_junction_group_audit.*` 中 `gate_status=passed` 的组级 RCSD 内部 Road / Node，并统一加入 F-RCSD；Step3 不重新判定可替换性。
- 输出 F-RCSD Road / Node，`source=1` 表示 RCSD，`source=2` 表示 SWSD。
- 待重建语义路口 C 来自 replaceable Segment 的 `pair_nodes + junc_nodes`。
- 若 C 的原 main node 被删除，需要重新选择 main node，并让 C 内 Node 继承原 main node 的 `kind / grade / kind_2 / grade_2 / closed_con`。

Step3 当前提供独立运行脚本，不改变现有 Step1 + Step2 内网脚本默认行为。输出文件名固定为 `t06_frcsd_road.* / t06_frcsd_node.*`；SWSD / RCSD 原始 `id` 冲突时保留原 id，依赖 `source` 区分，并写入 `t06_step3_id_collision_audit.*`；新 main node 选择优先级为原 main node、剩余 SWSD node 最小 id、加入 C 的 RCSD node 最小 id。

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

## Step3 独立脚本

Step3 脚本消费既有 T06 run root 下的 Step2 replaceable 成果：

```bash
.venv/bin/python scripts/t06_run_step3_segment_replacement.py \
  --t06-run-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t06_segment_fusion_precheck/t06_innernet_precheck \
  --swsd-segment /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/segment.gpkg \
  --swsd-roads /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T01/roads.gpkg \
  --swsd-nodes /mnt/d/TestData/POC_Data/first_layer_road_net_v0/T04/nodes.gpkg \
  --t05-phase2-root /mnt/d/Work/RCSD_Topo_Poc/outputs/_work/t05_innernet_experiment/t05_phase2_innernet
```

默认读取 `<t06-run-root>/step2_extract_rcsd_segments/t06_rcsd_segment_replaceable.gpkg`，若同目录存在 `t06_special_junction_group_audit.json` 则自动消费其中 passed 特殊路口组内部 RCSDRoad / RCSDNode；也可用 `--step2-special-junction-group-audit` 显式指定。Step3 输出写入同一 run root 的 `step3_segment_replacement/`。

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

- 用 `center_x / center_y / size_m` 或 `radius_m` 构建 EPSG:3857 方形窗口；`size_m` 表示正方形边长，`radius_m` 表示中心到边界距离。
- 选中与窗口相交的 SWSD Segment。
- 根据选中 Segment 的 `roads / pair_nodes / junc_nodes` 补齐必要 SWSD roads / nodes。
- 保留窗口内上下文 SWSD roads / nodes，并补齐已选 SWSDRoad 的端点 Node。
- 保留相关 T05 relation，并按 relation 补齐 mapped RCSD semantic nodes。
- 保留窗口内 RCSDRoad / RCSDNode，以及连接 selected RCSD node 的 RCSDRoad，并补齐已选 RCSDRoad 的端点 RCSDNode。

默认范围标准：

- `XXXS = 250m`
- `XXS = 500m`
- `XS = 1000m`
- `S = 2000m`
- `M = 5000m`

可用 `--size-m` 显式指定正方形边长，或用 `--radius-m` 显式覆盖 profile 半径；两者同时提供时 `--radius-m` 优先。

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
  --size-m 1000
```

解包后 `slice/` 下包含 `swsd/segment.geojson`、`swsd/roads.geojson`、`swsd/nodes.geojson`、`t05_phase2/intersection_match_all.geojson`、`t05_phase2/rcsdroad_out.geojson`、`t05_phase2/rcsdnode_out.geojson` 与 `t06_input_slice_summary.json`。该输入切片包的目标是形成少量真实数据本地测试用例，因此还会额外生成：

- `README_t06_local_case.md`：解包目录内的本地用例说明。
- `audit/t06_local_case_manifest.json`：记录解包后本地输入相对路径、原始来源、选择范围、关键计数、依赖完整性审计和 replay 脚本位置。
- `audit/replay_t06_decoded_precheck.sh`：在本地仓库上复跑 T06 Step1 + Step2，输入全部指向解包后的 `slice/` 数据。
- `audit/replay_t06_decoded_step3_segment_replacement.sh`：在 Step1 + Step2 已产生 `t06_rcsd_segment_replaceable.gpkg` 后复跑 Step3。

本地复跑示例：

```bash
cd /path/to/decoded/t06-case
REPO_DIR=/path/to/RCSD_Topo_Poc bash audit/replay_t06_decoded_precheck.sh
REPO_DIR=/path/to/RCSD_Topo_Poc bash audit/replay_t06_decoded_step3_segment_replacement.sh
```

`slice/t06_input_slice_summary.json` 中的 `dependency_audit` 用于判断包内依赖是否完整：SWSD Segment 引用的 SWSDRoad、SWSD 语义节点、SWSDRoad 端点 Node、T05 映射出的 RCSD 语义节点、已选 RCSDRoad 端点 Node 均会被审计。`source_relation_missing_required_target_ids` 表示原始 relation 数据中缺少对应 target，不属于打包遗漏，而是可复现的业务输入现象。

## 关键规则

- `pair_nodes + junc_nodes` 按语义路口 ID 判定。
- `junc_nodes.kind_2 in {1,4096,8192}` 的节点不参与 Step1 `has_evd / is_anchor` 判定，也不进入 Step2 T05 relation 必检映射集合；`pair_nodes` 不适用该豁免。
- `is_anchor = fail4_fallback` 视为可融合 anchor。
- Step2 relation 只接受 `status = 0` 且 `base_id > 0`；必检集合为 `pair_nodes + 非豁免 junc_nodes`。
- Step2 要求 `pair_nodes` 表示两个不同 SWSD 语义路口；若 SWSD pair 两端相同，或 relation 后 RCSD pair 归一到同一个语义路口，分别以 `swsd_pair_nodes_not_distinct` / `rcsd_pair_nodes_not_distinct` 拒绝。
- Step2 RCSD 建图使用 `rcsdnode_out` 的 `mainnodeid / subnodeid` 做语义节点归一化，relation required nodes 与 RCSDRoad `snodeid / enodeid` 使用同一 canonical key 判定连通。
- Step2 把 `rcsdnode_out` 中按有效 `mainnodeid` 聚合出的全局 RCSD 语义路口组作为图边界与审计对象；组内所有 node 关联 road 均视为该语义路口的进入 / 退出道路，未映射到当前 Segment 的全局 RCSD 语义路口不能被当成普通通过节点，必须参与 seed pruning。
- Step2 buffer 审查以 SWSD Segment 50m buffer 筛选 RCSD 候选，RCSDRoad 使用 `intersects + 阈值`，并在构图前按 `formway` bit7/128 识别提前右转 road；提前右转 road 若两端均与非提前右转候选 road 形成二度链接，或属于 required semantic nodes 之间的必要 corridor，则保留参与构建，否则排除。
- Step2 不把 buffer 候选连通分量直接作为 RCSDSegment；必须先基于 required semantic nodes 构建最小 corridor 子图，再输出 retained roads。
- Step2 双向 Segment 的 corridor 路径选择会惩罚明显短于 SWSD Segment 的 required-to-required connector，避免用路口内短连接替代完整反向 road。
- Step2 识别 RCSDRoad `formway & 1024 != 0` 为调头口；当调头 road 两端均属于 retained corridor node 时，作为内部调头 road 保留。
- Step2 retained RCSDRoad 必须满足 `min_buffer_road_overlap_ratio` 覆盖审计；候选阶段可通过 `intersects + overlap length / endpoint` 宽松进入，但最终 retained Road 若覆盖率低于阈值，以 `retained_road_buffer_overlap_insufficient` 拒绝。retained RCSD 与 SWSD 的整体 50m buffer 覆盖不一致比例默认不得超过 `10%`，绝对长度默认不得超过 `20m`，任一超限即拒绝。
- Step2 buffer 裁剪对额外 T05 mapped semantic nodes 执行 seed-based pruning：处于 required corridor 内部的 seed 归为 `inner_nodes` 并可保留审计；触达孤立挂接或其它 out leaf 且不在 required corridor 内的 seed 归为 `out_nodes` 并剔除；retained graph 中若仍存在非 inner 的额外 mapped semantic node，则以 `unexpected_mapped_semantic_nodes` 拒绝。
- 双向 SWSD 的 pruning 保护范围包含 pair 两端正反向 directed corridor，避免提前裁掉另一侧 RCSD 主线。
- `swsd_directionality=dual` 的 retained RCSD graph 必须 pair 两端双向可达，否则以 `rcsd_not_bidirectional_for_swsd_dual` 拒绝。
- `swsd_directionality=single` 必须先由 SWSDRoad `snodeid / enodeid / direction` 推导 source/target，再构建一条覆盖全部 required semantic nodes 的同向 RCSD corridor；不得用 `pair_nodes` 顺序、`segmentid A_B` 顺序或反向可达兜底；不满足时以 `rcsd_directed_path_missing` 或 `swsd_single_direction_*` 拒绝。
- `kind_2=64` 环岛路口与 `kind_2=128` 复杂路口按 `pair_nodes + junc_nodes` 做特殊组门控：关联 Segment 必须全部可替换，否则该组所有原本可替换 Segment 均从 `replaceable` 移除，并输出 `t06_special_junction_group_audit.*`。
- `junc_nodes` 是内部通过 + 侧向阻断，不是 hard-stop。
- Step2 retained RCSD graph 的叶子端点只能是 `pair_nodes` 对应的 RCSD semantic nodes；`junc_nodes` 或其它节点成为 retained leaf endpoint 时以 `unexpected_retained_endpoint_nodes` 拒绝。
- Step2 不再执行 pair-to-pair BFS 路径搜索、主轴趋势、长度趋势或唯一性筛选；单向 source/target 只来自 SWSDRoad directed graph；`candidate_count` 表示通过 buffer 构建的候选数量，`replaceable_count` 表示通过特殊组门控后的最终可替换数量。

## 输出

Step1 输出：

- `t06_swsd_segment_candidates.gpkg/csv/json`
- `t06_swsd_segment_final_fusion_units.gpkg/csv/json`
- `t06_swsd_segment_rejected.gpkg/csv/json`
- `t06_step1_segment_stats.csv`
- `t06_step1_summary.json`

其中 `t06_swsd_segment_candidates` 是通过 EVD 基础检查后的 SWSD Segment 候选集；`t06_swsd_segment_final_fusion_units` 是通过 anchor / fallback 检查后的 SWSD Segment 最终可融合集合。Step1 不再输出旧命名 `evd_candidates` 与 `fusion_units`，避免重复输出相同业务成果。`t06_step1_segment_stats.csv` 输出总体与按 `sgrade` 分组的总量、EVD 候选量、最终可融合集合量。

Step2 输出：

- `t06_rcsd_segment_candidates.gpkg/csv/json`
- `t06_rcsd_segment_replaceable.gpkg/csv/json`
- `t06_rcsd_segment_rejected.gpkg/csv/json`
- `t06_rcsd_buffer_segments.gpkg/csv/json`
- `t06_rcsd_buffer_segment_rejected.gpkg/csv/json`
- `t06_special_junction_group_audit.gpkg/csv/json`
- `t06_step2_summary.json`

其中 `t06_rcsd_buffer_segments` 是 buffer 构建成果；`t06_rcsd_segment_candidates` 为 buffer 成功构建的候选；`t06_rcsd_segment_replaceable` 为经过全部硬审计与特殊路口组门控后的最终可替换集合，不再表示 BFS 路径候选。
`t06_step2_summary.json` 同时记录 RCSD 视角覆盖统计：全量 RCSDRoad 数量 / 长度、最终可替换 Segment 引用的去重 RCSDRoad 数量 / 长度，以及引用次数口径的数量 / 长度。

Step3 输出：

- `t06_frcsd_road.gpkg/csv/json`
- `t06_frcsd_node.gpkg/csv/json`
- `t06_step3_unreplaced_rcsd_roads.gpkg/csv/json`

其中 `t06_step3_unreplaced_rcsd_roads` 是 Step3 审计输出，记录输入 RCSDRoad 中未被 Step2 replaceable Segment 使用、也未通过 `t06_special_junction_group_audit.*` 的 passed 特殊路口组进入 F-RCSD 替换结果的 Road。
