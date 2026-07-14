# P02 武汉局部实验验证报告

## 1. 验证结论

- 模块：`p02_wuhan_local_experiment`
- 生命周期：`Active POC / 成果模块`
- 最终运行：`p02_wuhan_local_20260714_run09`
- 总体判定：`passed_with_user_confirmed_endpoint_overrides`
- 分支：`codex/p02-wuhan-local-experiment-20260714`

run09 复用 run08 已从完整原始输入构建并验证的 T08/T01/T05 与 T06 Step1/Step2 成果，只重跑本轮唯一归属修复涉及的 T06 Step3。RCSDRoad copy-on-write 工作副本仅应用 `modules/p02_wuhan_local_experiment/endpoint_overrides/p02_confirmed_endpoint_overrides.csv` 登记的 9 项用户确认 `SNodeId/ENodeId` 修正。原始文件未修改、未裁剪；人工锚定关系未修改；没有使用 `NodeLid/CrossLid`，也没有在运行时用同坐标或最近点推断端点。

端点修正后，3 个锚定完整的重点 Segment 均完成替换；缺少正式锚定的 `521458225_600688320` 保持 SWSD。T06 Step3 共 7/7 个普通 Segment 替换成功，最终 F-RCSD 为 206 条 Road、243 个 Node，正式 `final_frcsd_topology_fail_count=0`。其中 58 条 `source=1` Road 唯一归属、4 条无 Segment owner、0 条多归属；4 条无归属 Road 由 3 条特殊路口内部 Road 和 1 条 connectivity Road 构成。

## 2. 输入、端点修正与 CRS

- 原始输入根：`E:\TestData\XiAn_Test\result\5524176501019109_5524182406597110`
- run09 根：`outputs/_work/p02_wuhan_local_experiment/p02_wuhan_local_20260714_run09`
- 端点白名单：`modules/p02_wuhan_local_experiment/endpoint_overrides/p02_confirmed_endpoint_overrides.csv`
- 端点修正审计：`02a_rcsd_endpoint_override/p02_rcsd_endpoint_override_audit.json`
- 输入完整性审计：`13_qa/p02_input_integrity_audit.json`
- GIS QA：`13_qa/p02_gis_qa.json`
- 重点 Segment 审计：`13_qa/p02_target_segment_audit.csv`
- QGIS 分析包：`outputs/_work/p02_wuhan_local_experiment/p02_wuhan_local_20260714_run09/14_qgis`

Tool1 staged 的 4 份 GeoJSON 与原始文件 SHA-256 一致。输入规模为 SWSD Node 143、SWSD Road 163、RCSDNode 655、RCSDRoad 469，原始层 CRS 均为 `EPSG:4326`。9 项修正均通过 Road 唯一、旧值精确、新 Node 唯一存在和白名单一致性校验；修正前后 Road 数量、ID 集合和几何逐要素不变，仅 9 个登记属性单元变化。原始 RCSD 缺失端点数为 9，工作副本降为 0。

T08 Tool3/Tool4/Tool5、T01、T05、T06 工作层为 `EPSG:3857`；QGIS 工程 CRS 为 `EPSG:3857`，原始 `EPSG:4326` 图层由 QGIS 动态投影。审计所覆盖矢量层均满足几何非空、几何有效和非空 ID 唯一。

## 3. T08、T01 与人工关系

- 正式顺序：`Tool1 -> Tool3 -> Tool6 -> 人工修正 609020493 -> Tool4 -> Tool5`；RCSD copy-on-write 端点修正在 Tool1 后独立执行，不改变 SWSD 工具顺序。
- Tool6 自动候选 3 条；人工将 `609020493.grade/grade_2` 设为 2，Tool4 形成 `kind_2=2048`。正式 Tool6 规则未修改。
- Tool4/Tool5 均输出 143 个 Node、163 条 Road；Tool5 构建 10 个复杂路口、更新 21 个 Node。
- 人工关系按 T11 格式落盘：原始 16 条，canonical 转换后 12 条，阻断 0、冲突 0、selected ID 缺失 0。
- T01 输出 109 个 Segment；没有正式锚定关系的 Segment 不进入 replacement plan。

## 4. T05 / T06 验证

### T05 Phase2

- 输入：完整 469 条修正工作副本 RCSDRoad、655 个 RCSDNode、143 个 final SWSD Node、12 个人工目标。
- 12/12 关系发布成功且图可消费；blocking error 0、cardinality blocking error 0。
- 输出：474 条 RCSDRoad、660 个 RCSDNode、10 条拆分 Road、5 个生成 Node、10 个分组 Node。
- `summary.passed=true`；所有 RCSDRoad `SNodeId/ENodeId` 均可解析到工作副本 RCSDNode。

### T06

- Step1：9 个最终融合单元，98 个 Segment 因 `has_evd_missing` 拒绝。
- Step2：7 个可替换、2 个拒绝、11 个 ready plan action；其中 7 个为标准 Segment action、4 个为复杂路口内部 action。
- Step3：7/7 个标准 Segment 替换成功；新增 RCSDRoad 62、移除 SWSDRoad 19；最终 F-RCSD Road 206、Node 243；Road/Node collision 均为 0。
- Road owner 收口：58 条唯一 Segment owner、3 条特殊路口内部无 owner、1 条 multi-Segment connectivity 无 owner、最终多 owner 数 0。
- 所有进入替换计划的 Segment 都具有完整正式锚定，缺锚违规数为 0。
- 诊断 topology audit 有 1 行 geometry coverage fail，但正式 `final_frcsd_topology_fail_count=0`、`segment_transition=0`、`independent_attachment=0`。

重点 Segment 结果：

| Segment | 正式锚定 | 最终结果 | 证据 |
| --- | --- | --- | --- |
| `3086610_609284657` | 完整 | `replaced/source_1` | 显式 RCSD 图双向可达；38 条最终 carrier 且均为唯一归属 Road，包含 `5855296278768589`、`5855295910117496`，并拥有 4 段并行通道 |
| `521458225_600688320` | 缺 `600688320` | `retained_swsd` | `has_evd_missing`，未进入 Step2、无 replacement plan |
| `521458225_612028267` | 完整 | `replaced/source_1` | 6 条 RCSDRoad，Step2/Step3 通过 |
| `609020493_61493884` | 完整 | `replaced/source_1` | 5 段通道为 `5855295910117380 -> 5855296278768752 -> 5855296278768753 -> 5855295910117379 -> 5855296278768576`，有序覆盖 RCSD 中间锚点 `5855296278770685 -> 5855296278770582` |

原 run07 的错误在于距离/视觉后处理把 4 段通道分给小 Segment，再用相邻 plan 的 5 段 peer 通道代替当前 Segment 的中间锚点覆盖。run08 固定优先级为“正式锚定关系 > required junction 有序相对位置 > 几何距离/视觉偏差”；run09 在此基础上进一步执行 Road owner 唯一收口。5 段锚点通道归属 `609020493_61493884`，4 段通道 `5855295910117399 / 5855295910117397 / 5855295910117569 / 5855296278768716` 归属 `3086610_609284657`。全量 `owned_frcsd_road_ids` 重复归属数和最终 `t06_swsd_segment_ids` 多值数均为 0。

## 5. GIS、QGIS、回归与性能可验证性

- `13_qa/p02_gis_qa.json` 全部自动检查为 true：原始 hash、完整数据规模、9 项端点修正、目标通路、锚定门禁、替换结果、几何与最终拓扑均可追溯。
- `609020493_61493884` 的 5 段通道由当前 Segment 自身有向连通并依序经过两个中间锚点；相对 SWSD 走廊仍存在空间偏移，诊断行 `segment_corridor_coverage_dropped_after_replacement` 保留为人工视觉复核项，不计入正式 topology fail。
- 道路面数据缺失，in-road coverage overlay gate 为 `not_run_unavailable`；未伪造道路面或覆盖率 PASS。
- QGIS 3.40.14 LTR：56/56 图层有效、11 个分组、相对路径、0 个缺失数据源、0 个绝对数据源引用；工程回读、内嵌 XML 解析和预览渲染均通过。
- Linux 正式 GIS 测试环境：本轮 T06 模块专项回归 `418 passed`；唯一归属定向回归 `38 passed`，输出压缩与 ownership 聚焦回归 `5 passed`。
- 所有本轮受治理源码/测试文件均小于 100KB；`git diff --check` 无空白错误。

## 6. 已修改 / 已验证 / 待确认

### 已修改

- 保留 9 项显式端点白名单与 copy-on-write 工作副本；本轮没有新增或修改人工锚定 relation。
- 保留 T06 并行走廊归属优先级，并新增最终 Road owner 收口：普通 Road 最多一个 Segment owner；特殊路口内部/连通补充 Road 无 owner；`path_corridor_group` 不再产生多 owner。
- 同步 T06/P02 契约、SpecKit、run09 QA 与 QGIS 分析包。

### 已验证

- 原始输入 hash 不变；469 条 RCSDRoad 数量、ID、几何不变，仅 9 个登记属性单元变化；工作副本缺失端点 9 -> 0。
- 3 个锚定完整重点 Segment 均替换成功；缺锚 Segment 保持 SWSD；`5855296278768589`、`5855295910117496` 已进入大 Segment 替换结果。
- T05 12/12 关系成功并可消费；T06 7/7 标准 Segment 替换成功；正式最终 topology fail 为 0。
- 小 Segment 的 5 段锚点通道与大 Segment 的 4 段通道归属正确；两者 peer 字段为空，全量唯一 Road 归属无重复。
- 原 8 条多归属 Road 已变为 4 条唯一归属、3 条特殊路口内部无归属、1 条 connectivity 无归属；最终多归属数为 0。
- QGIS 工程机器回读与预览通过；本轮 T06 418 项回归全部通过。

### 待确认

- `609020493_61493884` 的正确 RCSD 通道与 SWSD 几何走廊存在偏移，已按用户确认拓扑发布并保留人工视觉复核标记；可在 QGIS `00_目标问题复核` 分组直接对照。
- `521458225_600688320` 缺少 `600688320` 的正式锚定；在用户补充关系前继续保持 SWSD。
- 道路面与导流带数据补齐前，T07/T03/T04 及 in-road coverage overlay gate 仍不可执行。
