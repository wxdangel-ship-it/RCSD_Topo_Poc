# 03 Input Output Contract

## 输入

- `swsd_segment_path`：T01 `segment.gpkg`。
- `swsd_roads_path`：SWSD road body；Step2 使用 `id / snodeid / enodeid / direction` 推导单向 Segment 的真实 source/target。
- `swsd_nodes_path`：final `nodes.gpkg`；Step2 使用 `id / mainnodeid / subnodeid` 将 SWSDRoad endpoint 归一到 SWSD 语义节点后判断单向可达。
- `intersection_match_path`：T05 Phase 2 `intersection_match_all.geojson`。
- `rcsdroad_path`：T05 Phase 2 `rcsdroad_out.gpkg`。
- `rcsdnode_path`：T05 Phase 2 `rcsdnode_out.gpkg`，Step2 使用 `id / mainnodeid / subnodeid` 把 RCSDRoad raw endpoint 归一到 RCSD 语义主节点。

输入文件全部只读。缺少 CRS 或关键字段缺失 / 非法时，模块不得静默猜测，应进入 rejected 或显式抛出输入错误。

## Step1 输出

- `t06_swsd_segment_candidates.gpkg/csv/json`
- `t06_swsd_segment_final_fusion_units.gpkg/csv/json`
- `t06_swsd_segment_rejected.gpkg/csv/json`
- `t06_step1_segment_stats.csv`
- `t06_step1_summary.json`

`t06_swsd_segment_candidates` 是通过 EVD 基础检查后的 SWSD Segment 候选集；`t06_swsd_segment_final_fusion_units` 是通过 anchor / fallback 检查后的最终可融合集合。旧命名 `evd_candidates / fusion_units` 不再物理输出。`t06_step1_segment_stats.csv` 输出总体与按 `sgrade` 分组的总量、EVD 候选量、最终可融合集合量。

## Step2 输出

- `t06_rcsd_segment_candidates.gpkg/csv/json`
- `t06_rcsd_segment_replaceable.gpkg/csv/json`
- `t06_rcsd_segment_rejected.gpkg/csv/json`
- `t06_rcsd_buffer_segments.gpkg/csv/json`
- `t06_rcsd_buffer_segment_rejected.gpkg/csv/json`
- `t06_special_junction_group_audit.gpkg/csv/json`
- `t06_step2_summary.json`

`t06_rcsd_buffer_segments` 是 Step2 buffer 构建成果；`t06_rcsd_segment_candidates` 是 buffer 成功构建的 RCSDSegment 候选；`t06_rcsd_segment_replaceable` 是经过全部硬审计与特殊路口组门控后的最终可替换集合，不再表示 pair-to-pair BFS 路径候选。
`t06_special_junction_group_audit` 记录 `kind_2=64/128` 特殊语义路口的关联 Segment、组门控状态、映射 RCSD 语义路口、组内 RCSDNode 与内部 RCSDRoad。
`t06_step2_summary.json` 必须记录 RCSDRoad 覆盖统计：全量 RCSDRoad 去重数量 / 长度、最终可替换 Segment 引用的去重 RCSDRoad 数量 / 长度、按引用次数累计的 RCSDRoad 数量 / 长度，以及 replaceable 引用缺失数量。

## Step3 输出

Step3 输出目录：

```text
<out_root>/<run_id>/step3_segment_replacement/
```

输出：

- `t06_frcsd_road.gpkg/csv/json`
- `t06_frcsd_node.gpkg/csv/json`
- `t06_step3_replacement_units.gpkg/csv/json`
- `t06_step3_swsd_frcsd_segment_relation.gpkg/csv/json`
- `t06_step3_junction_rebuild_audit.gpkg/csv/json`
- `t06_step3_removed_swsd_roads.csv/json`
- `t06_step3_removed_swsd_nodes.csv/json`
- `t06_step3_added_rcsd_roads.csv/json`
- `t06_step3_added_rcsd_nodes.csv/json`
- `t06_step3_unreplaced_rcsd_roads.gpkg/csv/json`
- `t06_step3_id_collision_audit.gpkg/csv/json`
- `t06_step3_summary.json`

F-RCSD Road / Node 必须包含 `source` 字段：RCSD 来源为 `1`，SWSD 来源为 `2`。
F-RCSD Road / Node 原始 `id` 冲突不作为拒绝条件，必须写入 `t06_step3_id_collision_audit.*`。
Step3 默认从 Step2 replaceable 同目录读取 `t06_special_junction_group_audit.json`，并消费其中 `gate_status=passed` 的特殊路口组内部 RCSDRoad / RCSDNode；`t06_step3_unreplaced_rcsd_roads` 保留未进入 replaceable 或 passed 特殊组替换结果的原始 RCSDRoad 几何与属性，并增加未替换状态、审计原因、source 与长度字段，作为 RCSD 视角的遗漏审计结果。

`t06_step3_swsd_frcsd_segment_relation` 是面向下游 T09 的稳定关系证据，用于表达每个 SWSD Segment 在 F-RCSD 中的承载结果，而不是表达 Road 级限制结论。关系状态包括：

- `replaced`：该 SWSD Segment 已由 RCSD corridor 替换，`frcsd_road_ids` 必须指向 `t06_frcsd_road` 中 `source=1` 的 Road。
- `retained_swsd`：该 SWSD Segment 未被替换，仍由原 SWSD Road 承载，`frcsd_road_ids` 必须指向 `t06_frcsd_road` 中 `source=2` 的 Road。
- `failed`：该 SWSD Segment 无法建立稳定 F-RCSD 承载关系，必须在 `relation_reason / risk_flags` 中说明原因。

关系输出至少包含：

- `swsd_segment_id`
- `relation_status`
- `relation_reason`
- `swsd_pair_nodes`
- `swsd_junc_nodes`
- `junc_kind2_exempt_nodes`
- `swsd_road_ids`
- `removed_swsd_road_ids`
- `frcsd_road_ids`
- `frcsd_road_source_values`
- `rcsd_pair_nodes`
- `rcsd_junc_nodes`
- `junction_c_ids`
- `swsd_to_frcsd_node_map`
- `source_mix`
- `risk_flags`

下游不得根据同名 Road ID 假设 SWSD 与 F-RCSD 已匹配；必须使用本关系输出中的 `swsd_segment_id + relation_status + frcsd_road_ids + swsd_to_frcsd_node_map` 建立 Arm 级承载关系。

## 文本证据包 helper 输出

T06 模块内 `text_bundle.py` 提供非官方压缩 / 解压 helper，不新增 repo CLI。默认 compact 包输出：

- `t06_segment_fusion_precheck_evidence_bundle.txt`
- `t06_segment_fusion_precheck_evidence_bundle_size_report.json`

文本包默认自动分片，单个 `.txt` 分片上限为 `250KB`，可通过 `--max-text-size-bytes` 覆盖。第一片使用默认输出名或用户指定的 `--out-txt`，第二片起按 `<stem>.part_0002_of_000N.txt` 命名。解包 helper 接受任意一个分片路径，自动读取同目录其它分片、校验完整 payload SHA256 后还原。

包内记录：

- `audit/t06_input_manifest.json`：与内网端到端脚本同形的输入路径、T05 Phase 2 根目录、解析后的六个输入文件、参数、文件大小与 SHA256。
- `audit/replay_t06_run_innernet_precheck.sh`：可复跑命令。
- `run/step1_identify_fusion_units/` 与 `run/step2_extract_rcsd_segments/`：默认包含 summary、JSON / CSV 审计输出；显式 `--include-output-vectors` 才包含 GPKG。
- `inputs/`：仅显式 `--include-input-files` 时包含六个原始输入文件副本。

输入切片包额外支持 `center_x / center_y / profile_id / size_m / radius_m`，并输出：

- `slice/swsd/segment.geojson`
- `slice/swsd/roads.geojson`
- `slice/swsd/nodes.geojson`
- `slice/t05_phase2/intersection_match_all.geojson`
- `slice/t05_phase2/rcsdroad_out.geojson`
- `slice/t05_phase2/rcsdnode_out.geojson`
- `slice/t06_input_slice_summary.json`

默认 profile 半径为 `XXXS=250m / XXS=500m / XS=1000m / S=2000m / M=5000m`，显式 `--size-m` 可按中心点正方形边长选取范围，显式 `--radius-m` 可覆盖 profile 半径且优先于 `--size-m`。输入切片必须补齐已选 SWSDRoad / RCSDRoad 的 `snodeid / enodeid` 端点 Node，避免 road endpoint 引用缺失。
外部 size report 与解包后的 `t06_evidence_size_report.json` 必须保留 `limit_bytes / within_limit / split_bundle`，用于审计分片上限、分片数量和每片实际大小。

输入切片包的最终业务用途是“少量真实数据本地测试用例”，因此解包内容除六个 T06 输入文件外，还必须包含本地 case manifest、用例 README、Step1+Step2 replay 脚本和 Step3 replay 脚本。replay 脚本不得指向原始内网绝对输入路径，必须以解包目录为 `CASE_ROOT` 引用 `slice/` 下的数据；原始路径仅保留在 manifest 中用于审计追溯。

`slice/t06_input_slice_summary.json` 必须包含 `dependency_audit`，至少覆盖：

- Segment 引用的 SWSDRoad 是否已入包；
- Segment 引用的 `pair_nodes / junc_nodes` 对应 SWSDNode 是否已入包；
- 已选 SWSDRoad 的端点 Node 是否已入包；
- T05 relation 映射出的 RCSD 语义节点是否已入包；
- 已选 RCSDRoad 的端点 Node 是否已入包；
- 原始 relation 数据缺失的 required target，用于区分业务输入缺失和打包遗漏。

## GIS / 拓扑检查项

- CRS 与坐标变换正确性：所有输入通过仓库标准 vector reader 归一到处理 CRS；缺失 CRS 不静默猜测。
- 拓扑一致性：候选抽取不 silent fix 输入拓扑，required semantic node 连通覆盖、最小 corridor 子图构建与裁剪结果都进入审计。
- 语义节点裁剪可解释性：额外 T05 mapped semantic nodes 必须按 seed-based pruning 输出 `inner_node_ids / out_node_ids`，并在剔除 out 分支后重新校验 required semantic node 连通性；处于 required corridor 内部的额外 mapped semantic node 可作为 `inner_nodes` 保留审计，非 inner 且仍进入 retained graph 时输出 `unexpected_mapped_semantic_node_ids` 并拒绝；retained graph 叶子端点必须限定为 pair 对应 RCSD semantic nodes，非 pair 叶子端点输出 `unexpected_endpoint_node_ids` 并拒绝。
- 几何语义可解释性：SWSD 几何用于 buffer 窗口，RCSD 几何用于 `intersects + overlap threshold` 候选筛选与最终输出，不替代 relation / required semantic node 规则。
- 审计可追溯性：summary 记录输入路径、参数、计数、失败原因与输出路径。
- Step3 审计可追溯性：summary 必须记录 replaceable Segment 数量、删除 SWSDRoad / SWSDNode 数量、加入 RCSDRoad / RCSDNode 数量、特殊路口组消费数量与组级加入 RCSDRoad / RCSDNode 数量、未替换 RCSDRoad 数量 / 长度、重建 C 数量、main node 重选数量与失败原因。
- 文本证据包审计可追溯性：bundle 内必须保留输入路径、解析结果、文件大小、SHA256、参数与复跑命令。
- 性能可验证性：summary 记录输入规模、candidate 数、replaceable 数和 reject reason 统计。
- 语义节点归一化可追溯性：Step2 summary 记录 `rcsd_semantic_node_alias_count`，并在 `retained_node_ids` 等输出中使用 canonical RCSD semantic node id。
