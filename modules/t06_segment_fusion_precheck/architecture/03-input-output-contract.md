# 03 Input Output Contract

## 输入

- `swsd_segment_path`：T01 `segment.gpkg`。
- `swsd_roads_path`：SWSD road body。
- `swsd_nodes_path`：final `nodes.gpkg`。
- `intersection_match_path`：T05 Phase 2 `intersection_match_all.geojson`。
- `rcsdroad_path`：T05 Phase 2 `rcsdroad_out.gpkg`。
- `rcsdnode_path`：T05 Phase 2 `rcsdnode_out.gpkg`，Step2 使用 `id / mainnodeid / subnodeid` 把 RCSDRoad raw endpoint 归一到 RCSD 语义主节点。

输入文件全部只读。缺少 CRS 或关键字段缺失 / 非法时，模块不得静默猜测，应进入 rejected 或显式抛出输入错误。

## Step1 输出

- `t06_swsd_segment_evd_candidates.gpkg/csv/json`
- `t06_swsd_segment_candidates.gpkg/csv/json`
- `t06_swsd_segment_fusion_units.gpkg/csv/json`
- `t06_swsd_segment_final_fusion_units.gpkg/csv/json`
- `t06_swsd_segment_rejected.gpkg/csv/json`
- `t06_step1_summary.json`

`t06_swsd_segment_candidates` 是通过 EVD 基础检查后的 SWSD Segment 候选集；`t06_swsd_segment_final_fusion_units` 是通过 anchor / fallback 检查后的最终可融合集合。旧命名 `evd_candidates / fusion_units` 保留为兼容输出。

## Step2 输出

- `t06_rcsd_segment_candidates.gpkg/csv/json`
- `t06_rcsd_segment_replaceable.gpkg/csv/json`
- `t06_rcsd_segment_rejected.gpkg/csv/json`
- `t06_rcsd_buffer_segments.gpkg/csv/json`
- `t06_rcsd_buffer_segment_rejected.gpkg/csv/json`
- `t06_step2_summary.json`

`t06_rcsd_buffer_segments` 是 Step2 正式主成果；`t06_rcsd_segment_candidates` 与 `t06_rcsd_segment_replaceable` 为兼容输出，均由 buffer 成功结果派生，不再表示 pair-to-pair BFS 路径候选。

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

输入切片包额外支持 `center_x / center_y / profile_id / radius_m`，并输出：

- `slice/swsd/segment.geojson`
- `slice/swsd/roads.geojson`
- `slice/swsd/nodes.geojson`
- `slice/t05_phase2/intersection_match_all.geojson`
- `slice/t05_phase2/rcsdroad_out.geojson`
- `slice/t05_phase2/rcsdnode_out.geojson`
- `slice/t06_input_slice_summary.json`

默认 profile 半径为 `XXXS=250m / XXS=500m / XS=1000m / S=2000m / M=5000m`，显式 `--radius-m` 可覆盖。
外部 size report 与解包后的 `t06_evidence_size_report.json` 必须保留 `limit_bytes / within_limit / split_bundle`，用于审计分片上限、分片数量和每片实际大小。

## GIS / 拓扑检查项

- CRS 与坐标变换正确性：所有输入通过仓库标准 vector reader 归一到处理 CRS；缺失 CRS 不静默猜测。
- 拓扑一致性：候选抽取不 silent fix 输入拓扑，required semantic node 连通覆盖、最小 corridor 子图构建与裁剪结果都进入审计。
- 语义节点裁剪可解释性：额外 T05 mapped semantic nodes 必须按 seed-based pruning 输出 `inner_node_ids / out_node_ids`，并在剔除 out 分支后重新校验 required semantic node 连通性；retained graph 中仍存在 required / optional allowed 以外 mapped semantic nodes 时输出 `unexpected_mapped_semantic_node_ids` 并拒绝；同一 RCSD base node 若同时映射到本 Segment 以外 SWSD 语义节点，也按额外 mapped semantic node 拒绝；retained graph 叶子端点必须限定为 pair 对应 RCSD semantic nodes，非 pair 叶子端点输出 `unexpected_endpoint_node_ids` 并拒绝。
- 几何语义可解释性：SWSD 几何用于 buffer 窗口，RCSD 几何用于 `intersects + overlap threshold` 候选筛选与最终输出，不替代 relation / required semantic node 规则。
- 审计可追溯性：summary 记录输入路径、参数、计数、失败原因与输出路径。
- 文本证据包审计可追溯性：bundle 内必须保留输入路径、解析结果、文件大小、SHA256、参数与复跑命令。
- 性能可验证性：summary 记录输入规模、candidate 数、replaceable 数和 reject reason 统计。
- 语义节点归一化可追溯性：Step2 summary 记录 `rcsd_semantic_node_alias_count`，并在 `retained_node_ids` 等输出中使用 canonical RCSD semantic node id。
