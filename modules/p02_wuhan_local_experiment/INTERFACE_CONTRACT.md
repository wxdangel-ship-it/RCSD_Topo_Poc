# P02 - INTERFACE_CONTRACT

## 1. 契约边界

- 模块 ID：`p02_wuhan_local_experiment`
- 生命周期：`Active POC / 成果模块`
- 稳定范围：人工关系落盘、Tool5 后 canonical 转换、内网武汉单 Case 编排、实验 manifest、QGIS 工程与 QA 收口。
- 非目标：不新增算法规则，不替代 T08/T01/T05/T06。

## 2. 输入契约

- Tool5 最终 SWSD Nodes：`id / mainnodeid`，CRS 必须可解析。
- 原始人工关系：T11 八字段 CSV。
- RCSDNode/RCSDRoad ID 集合：用于 selected ID 存在性检查。
- Tool1 转换后的完整 SWSD/RCSD Road 与 Node：要素不得因缺失端点或缺少人工关系被裁剪。
- 用户确认的 P02 临时端点覆盖：`road_id / endpoint_field / expected_old_node_id / replacement_node_id`；当前唯一白名单为 `endpoint_overrides/p02_confirmed_endpoint_overrides.csv` 的 9 项。清单包含原两项覆盖以及 2026-07-14 全量端点审计后由用户明确授权的 7 项新增覆盖；执行时只消费清单，不运行几何匹配或最近点推断。
- 内网输入目录：必须包含 `node.geojson / road.geojson / RCSDNode.geojson / RCSDRoad.geojson`，入口先逐字节复制到新 run root，再由 Tool1 转换；不得在原目录旁写 GPKG。

本批次人工关系类型：13 条 `1v1_rcsd_junction`、1 条 `1v1_rcsd_road`、2 条 `1vN_rcsd_road`。1vN `selected_ids` 用 `|` 分隔。

## 3. 输出契约

- `p02_manual_relations_raw.csv`：不可变原始关系。
- `p02_manual_relations_converted.csv`：T05 消费的 T11 格式关系。
- `p02_manual_relation_transform_audit.csv`：逐行转换 lineage。
- `p02_manual_relation_transform_summary.json`：数量、冲突、缺失和去重 summary。
- `p02_input_integrity_audit.json`：原始输入与工作副本的要素数、ID 集合、缺失端点引用、CRS 和 hash 审计；必须把用户确认的临时覆盖与其它未处理缺失端点分开统计。
- `p02_rcsd_endpoint_override_audit.json`：临时端点覆盖清单中的 Road、字段、旧值、新值、用户确认来源、输入/输出 hash、要素数/ID/几何不变校验；不得出现清单外属性变更、`NodeLid/CrossLid` 或几何推断来源。
- `p02_confirmed_endpoint_overrides.csv`：本批次 9 项用户确认白名单的运行副本，必须与模块登记清单逐字节一致。
- `p02_run_manifest.json`：跨阶段输入、参数、输出、状态和环境。
- `13_qa/p02_current_result_validation.json`：当前武汉基线硬校验，包括 109 Segment、12 条 T05 relation、7 个 T06 替换、206/243 F-RCSD、RCSD Road 唯一普通 Segment 归属与正式拓扑失败数 0。
- `14_qgis/p02_wuhan_local_analysis.qgz`：使用相对 datasource 的原始/中间/最终数据分析工程；同目录必须含 layer manifest、预览图和 QGIS 回读 QA。

## 4. 状态

`transform_status` 值域：`unchanged / remapped / merged_to_1vN / deduplicated / conflict / missing_target`。

同一 canonical target 下，只要所有来源关系同属 RCSD junction 或同属 RCSDRoad，就按来源顺序合并 `selected_ids` 并依据并集数量发布 1v1/1vN；junction 与 road 混合才属于 conflict。

出现 `conflict / missing_target` 时，converted CSV 不得交给 T05。

## 5. 入口契约

- 核心正式入口：`.venv/bin/python scripts/p02_run_wuhan_internal_case.py --input-dir <raw-dir>`；唯一必填参数为 `--input-dir`，可选 `--out-root / --run-id / --qgis-python`。`--qgis-mode skip` 仅用于开发诊断，正式内网执行不得使用。
- WSL 内网固定 Case 包装入口：`bash scripts/p02_run_wuhan_innernet_case.sh [raw-input-dir]`。无参数时固定使用仓库 `/mnt/d/Work/RCSD_Topo_Poc`、输入 `/mnt/d/TestData/数据整理/result/result/5524176501019109_5524182406597110`、仓库 `.venv/bin/python` 与 `/usr/bin/python3` PyQGIS；可通过 `P02_REPO_DIR / P02_INPUT_DIR / P02_OUT_ROOT / P02_RUN_ID / P02_PYTHON_BIN / QGIS_PYTHON_BIN / P02_LOG_FILE` 显式覆盖。
- WSL 包装入口只做路径、四输入文件、仓库 Python 和 PyQGIS 前置检查，随后以 `--qgis-mode required` 转调核心正式入口；不得复制 P02 或 T08/T01/T05/T06 算法，也不得回退到系统普通 Python。
- WSL 包装入口必须将完整控制台日志保存在 `<out-root>/<run-id>.console.log`，并在核心入口返回后复核 manifest `17/17`、当前结果硬校验和 QGIS 工程写出/回读状态。
- 入口只能编排既有 T08/T01/T05/T06，不得在 P02 内复制或改写这些模块的算法。
- run root 必须全新且拒绝覆盖；任一阶段失败必须写入 manifest 并返回非 0。
- 默认必须发现 `python-qgis-ltr` 或 `python-qgis`，也可通过 `--qgis-python` / `QGIS_PYTHON_BIN` 指定。
- 模块内 callable：`transform_manual_relations(...)`、`apply_confirmed_endpoint_overrides(...)`、`apply_wuhan_t_junction_override(...)` 和 `run_wuhan_internal_case(...)`。

## 6. 验收

- 原始关系不被覆盖。
- converted target 唯一；1vN selected ID 不丢失。
- selected ID 可在指定原始 RCSD 输入定位。
- 冲突、缺失端点和未运行阶段均显式审计。
- 工作副本 Road/Node 数量、ID 集合和 Road 几何必须与 Tool1 转换结果一致；不得生成 local clip。除契约登记且旧值严格匹配的用户确认端点覆盖外，不得执行其它端点归一。
- 缺少正式 T05 relation 的 Segment 不得进入 T06 replacement plan；T06 继续执行方向、连通、buffer、required junction 与最终 topology 硬审计。
- 正式入口只有在当前武汉结果硬校验与 QGIS 工程写出/回读均通过时，才可发布 `status=passed`。
