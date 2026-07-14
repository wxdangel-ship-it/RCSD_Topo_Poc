# P02 武汉局部实验规格

**Feature Branch**: `codex/p02-wuhan-local-experiment-20260714`
**Created**: 2026-07-14
**Status**: Ready for implementation
**Input**: 在武汉局部实验数据上，以完整 SWSD/RCSD 原始要素运行 T08、T01、T05、T06，验证人工锚定驱动的 Segment 融合链路。

## 1. 目标与边界

P02 是 `Active POC / 成果模块`，模块 ID 为 `p02_wuhan_local_experiment`。本轮只编排并验证既有 T08、T01、T05、T06 能力，沉淀输入、人工关系、转换 lineage、阶段产物和 QA 结论；不替代这些模块的正式契约，不新增 repo CLI、root script、Makefile 目标、模块 `run.py` 或模块 `__main__.py`。

原始目录仍使用历史路径 `E:\TestData\XiAn_Test\result\5524176501019109_5524182406597110`，但数据 CRS/坐标和本轮正式模块命名统一按武汉局部实验解释。

缺少道路面、导流带与 RCSDIntersection，T07、T03、T04 不运行。P02 不伪造这些模块的业务成果；T05 Phase2 使用用户提供并经 Tool5 后 canonical 转换的 T11 格式人工关系。

## 2. 用户场景与测试

### US1 - 规范化武汉局部输入（P1）

作为实验负责人，我需要按 `Tool1 -> Tool3 -> Tool6 -> Tool4 -> Tool5` 处理 SWSD，使 T01 消费的是带有正式 `closed_con / kind_2 / grade_2` 的 copy-on-write 数据。

**独立验收**：五个阶段依次成功，输入不被覆盖，所有输出 CRS、要素数、字段和运行时间可追溯。

### US2 - 转换并落盘人工关系（P1）

作为人工锚定提供者，我需要保留原始关系，并在 Tool5 复杂路口聚合后将 SWSD 原始语义路口 ID 转为最终 canonical target，再按 T11 可消费字段落盘。

**独立验收**：16 条原始关系全部有转换审计；同 canonical target 下同对象类别关系合并为 1v1/1vN，junction/road 跨对象类别冲突必须阻断；转换 CSV 能被 T05 读取。

### US3 - 构建 Segment 并执行人工锚定融合（P1）

作为 POC 验证者，我需要运行 T01、T05 Phase2 和 T06 Step1-3，得到可解释的 Segment funnel、relation 发布、replacement plan 与 F-RCSD 拓扑结果。

**独立验收**：每个阶段有明确 passed/failed 状态；失败对象保持在审计和待补关系清单中，不静默补锚、不静默修复拓扑。

### US4 - 形成可复现 QA 证据（P2）

作为 QA，我需要确认 CRS、拓扑、几何语义、审计 lineage、性能和完整输入事实均有机器可读证据。

**独立验收**：输入 manifest、阶段 summary、关系 lineage、输入完整性审计、T05 graph consumability、T06 topology connectivity 和性能计时齐全。

### US5 - 全量保留原始 Road/Node（P1）

作为局部实验负责人，我需要完整保留用户提供的 SWSD/RCSD Road 与 Node，不以缺失端点或人工关系覆盖范围裁剪输入。

**独立验收**：T05 输入保留 Tool1 转换后的 469 条 RCSDRoad 与 655 个 RCSDNode，T01 输入保留完整 SWSD；不删除 Road、不补造 Node。用户确认的 9 项临时覆盖按白名单单独审计，覆盖后 RCSDRoad 缺失端点引用为 0。没有正式锚定关系的 Segment 不进入 replacement plan。

## 3. 五类职责视角

### 产品

- P02 回答“在缺少道路面/导流带时，人工锚定能否支撑 T01→T05→T06 局部实验”。
- 不把本次成功率直接解释为全量生产能力。

### 架构

- T08 负责字段归一和节点类型处理；T01 负责 Segment；T05 负责 relation/junctionization；T06 负责替换与拓扑审计；P02 只负责实验编排、关系转换和证据收口。
- `closed_connect` 是 `closed_con` 的正式输入别名，由 T08 Tool3 归一为 `closed_con`；T01 强规则继续只读取 `closed_con`。
- T03/T04/T07 缺失以显式 unavailable 状态表达，不生成伪成果。

### 研发

- 新增 P02 模块内 callable，用于生成 T11 格式原始关系、Tool5 后关系转换、冲突检查和 lineage 审计。
- 不新增正式执行入口；实际单次运行通过现有工具入口与 `outputs/_work` 下的一次性编排完成。

### 测试

- 覆盖 `closed_connect -> closed_con`、双字段一致/冲突、原字段保留。
- 覆盖关系 canonical 转换、重复合并、冲突阻断、RCSDNode 与 RCSDRoad 类型保持。
- 运行 T08/T01/P02/T05/T06 聚焦测试。

### QA

- CRS：输入 `EPSG:4326`，空间处理输出 `EPSG:3857`，T05 relation 为 CRS84/WGS84。
- 拓扑：4 个 SWSD 原始缺失端点引用继续作为输入完整性问题审计；9 个 RCSD 原始缺失端点引用已逐项找到几何精确一致 Node，并由用户明确授权形成 9 项显式覆盖白名单。要素仍全量进入流程，不补造、不 silent fix；覆盖必须逐项旧值校验并可追溯。
- 几何：人工 road relation 由 T05 投影/split；人工 node relation必须落到最终 RCSD graph 可消费语义节点。
- 审计：原始关系、转换关系、T05 发布关系和 T06 carrier 形成完整 lineage。
- 性能：记录各阶段 wall time、输入输出要素数和峰值资源信息（环境可取得时）。

## 4. 功能需求

- **FR-001**：P02 MUST 使用正式顺序 `Tool1 -> Tool3 -> Tool6 -> Tool4 -> Tool5`。
- **FR-002**：Tool4 MUST 直接消费本次 Tool6 输出；该批次视为用户已人工确认 `是否修复=1`。
- **FR-003**：Tool3 MUST 将仅有的 `closed_connect` copy-on-write 归一为 `closed_con`；两字段同时存在且值不等时 MUST 失败。
- **FR-004**：P02 MUST 保留 16 条原始人工关系，不得用转换结果覆盖。
- **FR-005**：Tool5 后 MUST 使用最终 SWSD Nodes 的有效 `mainnodeid`，无有效值时回退 `id`，生成 canonical `target_id`。
- **FR-006**：人工关系 MUST 按 T11 字段落盘：`case_id / swsd_segment_id / target_id / manual_relation_type / selected_ids / comment / source_manual_table / source_manual_xlsx`。
- **FR-007**：13 条 RCSDNode 关系 MUST 使用 `1v1_rcsd_junction`；RCSDRoad 关系中 `611463745` MUST 使用 `1v1_rcsd_road`，`521458225 / 612028267` MUST 使用 `1vN_rcsd_road` 并以 `|` 保存两个 selected road ID。
- **FR-008**：多个原始 target 转为同一 canonical target 时，同属 junction 或同属 road 的 selected ID MUST 并集合并并按基数发布 1v1/1vN；junction/road 跨对象类别混合 MUST 阻断 T05。
- **FR-009**：P02 MUST 跳过 T07/T03/T04，并在 manifest 中记录原因 `missing_road_surface_divstrip_and_rcsdintersection`。
- **FR-010**：缺失端点 MUST 进入 input integrity audit，不得生成虚构 Node或删除 Road；除 FR-017 登记的用户确认覆盖外不得改写端点。
- **FR-011**：T05 MUST 从 Tool1 转换后的完整 469 条 RCSDRoad/655 个 RCSDNode copy-on-write 运行，并消费转换后的 T11 CSV。
- **FR-012**：T06 MUST 只消费 T01 Segment、T05 relation/RCSD 输出和自身 replacement plan，不把人工原始关系直接当替换白名单。
- **FR-013**：所有运行输出 MUST 写入新的 P02 run root，不覆盖原始数据、既有 baseline 或其它模块 run root。
- **FR-014**：P02 MUST NOT 生成 local clip 或按人工锚定范围筛选 Road/Node；T05/T06 输入 ID 集合 MUST 可与 Tool1 转换结果核对。
- **FR-015**：P02/T05/T06 MUST NOT 使用 `CrossLid`、最近点或局部样本重写输入端点；如需启用该字段，必须另行确认正式语义与冲突边界。
- **FR-016**：没有正式 T05 relation 或未通过 T06 硬审计的 Segment MUST 保留 SWSD，MUST NOT 进入 ready replacement plan。
- **FR-017**：P02 MUST 在 Tool1 后、T05 前生成完整 RCSDRoad copy-on-write 工作副本，只执行 `modules/p02_wuhan_local_experiment/endpoint_overrides/p02_confirmed_endpoint_overrides.csv` 登记的 9 项用户确认覆盖。任一旧值不匹配、目标 Road 非唯一、新 Node 不唯一存在或运行副本与模块清单不一致时 MUST 失败；覆盖后 RCSDRoad 缺失端点引用 MUST 为 0；MUST NOT 读取 `NodeLid/CrossLid` 或在运行时用几何推断其它覆盖。

## 5. 成功标准

- **SC-001**：16/16 原始关系存在、可解析并有唯一 lineage 结果或明确冲突状态。
- **SC-002**：T08 五阶段与 T01/T05/T06 均产出阶段 summary；任一失败有可定位日志和输入路径。
- **SC-003**：T05 输出中转换后的每个非冲突 target 只有一条 relation；graph consumability 有明确结果。
- **SC-004**：T06 最终 Road/Node integrity、Segment connectivity、source consistency 无 silent fix；原始缺失端点单列审计。
- **SC-005**：P02 最终报告区分已处理、已替换、未替换、待补关系和数据边界问题。
- **SC-006**：T05 输入完整保留 469 条原始 RCSDRoad，包括 `5855295910117379` 与 `5855295910117517`；任何 Segment 是否替换仅由正式 relation 与 T06 replacement plan 决定。
- **SC-007**：端点覆盖审计证明只修改白名单登记的 9 个属性单元，RCSDRoad 数量仍为 469，Road ID 集合和几何逐要素不变；原始文件 hash 不变，工作副本 RCSDRoad 缺失端点数为 0。

## 6. 当前明确事实

- 输入要素数：SWSD Node 143、SWSD Road 163、RCSDNode 655、RCSDRoad 469。
- 16 条用户关系引用 16 个 SWSD target 与 18 个 RCSD selected ID，当前均已在原始输入中验证存在。
- SWSD Road 有 4 个端点引用缺失，继续只审计；原始 RCSDRoad 的 9 个缺失端点引用均存在几何精确一致的 RCSDNode，并已由用户授权按显式清单在 P02 copy-on-write 工作副本修正。
- 用户授权 `closed_connect` 与 `closed_con` 等价，并授权同步项目约束与相关模块契约。
