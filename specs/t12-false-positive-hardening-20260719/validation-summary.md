# Validation Summary：T12 false-positive hardening

## 1. 11 个 Segment

- 运行结果：11/11 passed，`not_assessable=0`。
- 目标结果：`7 excluded_false_positive / 4 confirmed_quality_issue`。
- 最终结果 CSV：`outputs/_work/t12_false_positive_hardening_20260719/t12_replay_final_20260719/t12_segment_replay_summary.csv`。
- 最终结果 JSON：`outputs/_work/t12_false_positive_hardening_20260719/t12_replay_final_20260719/t12_segment_replay_summary.json`。
- 每个 candidate 同时输出 `raw_failed_directions`、semantic 排除后的 `failed_directions`、`automatic_equivalence_basis` 和 `portal_constrained_semantic_status`。

| SegmentID | 结论 | 原始数据证据 |
| --- | --- | --- |
| `1520811_25466551` | 误报，自动排除 | raw `pair0_to_pair1` 缺失，但正式 portal 之间存在满足方向、长度、绕行和 corridor 门槛的语义 carrier。 |
| `1623512_508276240` | 确认质量问题 | `pair0_to_pair1` 在 raw 与语义 carrier 中均缺失。 |
| `1629816_1643047` | 误报，自动排除 | raw 单向缺失由受信 T07/T03 portal 间的语义 carrier 覆盖。 |
| `1878482_1881808` | 误报，自动排除 | raw 单向缺失由受信 T07/T03 portal 间的语义 carrier 覆盖。 |
| `1881810_1898171` | 误报，自动排除 | raw 双向 ID 连续性缺失，但两方向物理语义 carrier 均存在。 |
| `1888260_1921768` | 确认质量问题 | `pair1_to_pair0` 缺失，且 T06 原始证据为 `full_rcsd_graph_one_direction_only`。 |
| `1908169_1921764` | 误报，自动排除 | raw 双向 ID 连续性缺失，但两方向物理语义 carrier 均存在。 |
| `1921739_1921764` | 确认质量问题 | `pair0_to_pair1` 的 T07 alias 位于对应标准路口面外，不能作为受信 portal。 |
| `500636195_505415445` | 确认质量问题 | `pair1_to_pair0` 无语义路径，反向的 T07 alias 又位于标准路口面外。 |
| `722528_722529` | 误报，自动排除 | raw `pair0_to_pair1` 缺失，但受信 portal 间语义 carrier 存在。 |
| `722569_12927873` | 误报，自动排除 | raw 双向 ID 连续性缺失，但两方向物理语义 carrier 均存在。 |

误判共因不是 FRCSD 物理通行缺失，而是同一物理路口内 raw node ID/alias 被拆分，旧逻辑只认 raw 端点连续性。修复规则不包含任何 SegmentID：语义 carrier 只能用于排除 raw failure，必须包含非零物理 Road，并同时通过正式 portal、T07 标准面、内部 alias gap、方向、长度和 corridor 门槛；任一门槛失败仍保留质量问题。

11 个原始包内的显式 FRCSD 裁剪层均缺少部分 Road endpoint。兼容重放仅在同源拓扑完整切片与包内公共 Road/Node 的属性、几何和端点等价检查通过后使用；未改写输入，`silent_fix=false`。包审计见 `outputs/_work/t12_false_positive_hardening_20260719/package_audit/package_topology_compatibility_audit.csv`。

## 2. `1026960` 冻结基线

- 输入：`E:\TestData\POC_QA\T10\1026960` 原始证据及同批 T01/T05/T06 派生结果。
- 未提供 review decisions，全部结果来自 T12 自动 high-confidence decision。
- 新结果：`35 candidates / 10 confirmed / 25 excluded / 0 manual`。
- 与旧基线比较：confirmed ID diff=`0`，`candidate_id|issue_type` diff=`0`。
- 最终运行：`outputs/_work/t12_false_positive_hardening_20260719/1026960_final_semantic/t12_1026960_semantic_final_20260719/`。
- 运行时间：`6.720439s`；`1267` Segments、`4289` FRCSD Roads、`4762` FRCSD Nodes。

## 3. 自动测试

- T12 + T10 affected suite：`108 passed, 2 warnings`。
- `compileall`：T12 production、正式 T12 入口与 validation scripts 均通过。
- 生产源码 ID 扫描：11 个审计 ID 与 `1026960` 冻结 ID 均未写入生产规则。
- 源码体量：本轮 14 个变更/新增 `.py` 文件全部 `<100 KB`，最大为 `candidate_audit.py=23435 bytes`。
- `git diff --check`：通过，仅有工作区既有 LF/CRLF 提示。
- 覆盖：标准面外 T07 alias 不覆盖 raw failure；标准面/正式 portal 受信且内部 gap 合法时排除；内部 alias gap 超限时保留；semantic exclusion 使用独立 decision rule；输出契约包含新增审计字段。

## 4. GIS / QA Gate

- CRS：所有 11 个包和 `1026960` 均以 `EPSG:3857` 处理；manifest 记录输入 CRS 和是否发生转换。
- 拓扑：不做 silent fix；裁剪包端点不完整时先判定包缺口，再使用通过同源等价 Gate 的完整切片重放。
- 几何语义：语义 carrier 必须是有物理 Road 的有向路径；零长度 canonical alias 重叠不能充当物理通行。
- 可追溯性：每个方向保留 raw failure、语义 carrier 状态、portal 信任原因、decision rule、输入 hash、参数和运行环境。
- 可视 QA：11 个 DriveZone/road overlay Gate 全部通过，证据位于 `outputs/_work/t12_false_positive_hardening_20260719/qgis_drivezone_gate/`；DriveZone 仅作证据，不参与 verdict。
- 性能：11 个包累计 `52.448891s`；`1026960` 为 `6.720439s`，均写入 machine-readable summary/manifest。

## 5. 仓库级既有 Gate

- 标准 `pytest --collect-only`：`2182 tests collected`，但仓库现有两个同名 `test_text_bundle.py` 发生 import mismatch，收集退出 1。
- 为绕过上述既有收集冲突执行 `pytest -q --import-mode=importlib`：`2163 passed / 27 failed / 4 skipped / 2 warnings`。27 个失败位于未修改的 P01、T02、T04 和既有字段治理检查；其中字段治理检查命中未修改的 `carrier_graph.py`，不由本轮引入。本轮不扩大范围修复这些既有失败。
