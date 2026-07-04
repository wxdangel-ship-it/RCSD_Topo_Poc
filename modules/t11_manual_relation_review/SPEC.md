# T11 模块规格：人工 Relation 修复候选抽取

## 1. 模块定位

T11 是人工 relation / anchor 修复候选抽取模块。它只读取既有 T10 端到端 Case 结果，从 T01 Segment、T05 relation 发布层和 T06 替换审计层中提炼需要人工判断的 SWSD 语义路口候选。

T11 不修改 T05/T06/T09，不重跑 T06/T09，不把候选提升为 T06 白名单。候选输出只作为人工审计输入；后续人工结果应由 T05 消费并重新生成正式 relation。

## 2. 业务目标

- 从冻结 T10 Case root 中定位 T05/T06/T10 证据。
- 找出 Segment `pair node` 与 `junc node` 中没有正确建立 1v1 anchor 的 SWSD 语义路口。
- 找出因 relation 缺失、relation 不可图消费、pair anchor 或 required nodes 断连导致 Segment 无法替换的 SWSD 语义路口。
- 纳入无证据但 Segment 范围内存在 RCSD 候选的路口；无 RCSD 上下文的路口不作为高优先级。
- 以 Segment 下 SWSD Road 总长度为主要优先级，高优先级 Segment 中缺 anchor 的路口优先。
- 输出全量人工可填写审计表，并可带入既有局部人工填写结果。

## 3. 当前范围

### 3.1 正式支持

- 输入：已完成的 T10 Case root。
- 读取 T05 Phase2 的 `relation_graph_consumability_audit.csv`、`rcsd_junctionization_audit.csv`、`intersection_match_all.geojson`、`rcsdroad_out.gpkg`、`rcsdnode_out.gpkg`。
- 读取 T06 Step1/Step2 的 final fusion units、Step1 rejected、problem registry、rejected、buffer rejected、replacement plan 和 repair candidates。
- 读取 T01/T04 节点与 Segment 几何，用于 target 上下文和影响长度统计。
- 输出 relation 候选 CSV/GPKG、relation 人工模板 CSV、Segment anchor 全量人工审计 CSV、Segment anchor 人工模板 CSV 和 summary JSON。
- 固定输出 Segment 级“未替换 Segment 中有效路口没有可消费 1V1 relation”的人工审计 CSV/GPKG/XLSX。该表以 T06 Step3 未替换 Segment 为分母，避免混入已替换成功 Segment。
- 固定输出三张 Segment 审计拆分表：所有路口均有 Relation、所有路口均有证据但存在 Relation 缺口、存在无证据路口且需按 50m RCSD 上下文排序。
- 固定输出 Segment 级“全 1V1 relation 成功但 T06 未替换”审计 CSV/GPKG/XLSX，用于快速定位 relation 之外的 corridor、方向性、RCSD 数据质量或 T06 执行问题。
- 提供人工 Excel 重跑入口，直接读取三张 Segment 审计 Excel 中局部填写的可执行人工 relation，合并为 T05 可消费 CSV 后重跑 T05/T06，并输出修复前后指标对比。
- 提供内网人工重跑损失度量抽取入口，从 T11/T05/T06 运行成果中按收益降序输出人工 relation 漏锚与 `5_replaceable_scope_unreplaced` 策略问题清单；该入口只读运行目录，不修改输入成果。
- 提供 QGIS 人工 Relation 审计插件，作为表 2 / 表 3 两张 relation 缺口 Excel 的地图化编辑入口；插件 UI 单次加载其中一张 Excel 进行修订，按 `target_id` 去重展示任务，并将人工编辑立即同步写回当前 Excel 的 `manual_relation_type / selected_ids / comment` 三列。

### 3.2 当前非目标

- 不做人工回灌。
- 不修改 T05 relation。
- 不作为 T06 Step2 或 Step3 替换白名单。
- 候选抽取 callable 不重跑 T06/T09；人工 Excel 重跑入口只在用户明确提供人工标注后串联既有 T05/T06 脚本生成新 `_work` 结果。
- 不反推上游字段新语义。
- QGIS 插件不泛化为 T08 tool6 或其它质量审计平台，不替代 Excel 成为人工结果事实源。

## 4. 候选分类

| 分类 | 含义 |
|---|---|
| `relation_missing_or_invalid` | T06 relation mapping 或 problem registry 显示 pair relation 缺失、无效或不可用于替换。 |
| `relation_graph_unconsumable` | T05 relation graph consumability 显示 relation 不能被图消费。 |
| `required_nodes_disconnected_or_pair_anchor_issue` | T06 显示 required nodes 不连通、pair anchor 错配或 endpoint cluster 需上游修复。 |
| `no_evidence_but_rcsd_present_in_segment_scope` | SWSD 路口 `has_evd` 为空或否，但关联 Segment 范围内存在 RCSD 候选节点或道路。 |
| `uncertain_upstream_or_data_issue` | 证据不足以归入以上类别，但仍被 T06 阻断或要求审计。 |

## 5. Segment Anchor 审计口径

Segment Anchor 审计表是当前人工审计主入口：

- 候选来自受 T06/T01 证据覆盖的 Segment `pair node` 与 `junc node`。
- `junc node` 会按 `t01/roads.gpkg` 复算非提右 incident road 数；剔除 `formway` bit 128 的提前右转 Road 后若只剩不超过 2 条 Road，则不作为路口锚点候选。
- 已满足 `has_evd=yes`、`is_anchor=yes`、T05 success、relation graph 可消费且 graph status 为 `base_node_graph_incident` 的 1v1 anchor 不进入候选。
- 对每个候选聚合其影响 Segment 集合、最高优先级 Segment、Segment 总长度、T05 状态、T06 reject reason 和 RCSD 候选 ID。
- 输出全量候选，不按 Top 截断；人工只需填写局部行。
- 若提供既有人工 CSV，仅按 `target_id` 保留人工填写的 `manual_relation_type / selected_ids / comment`。
- 未人工填写且 Segment 范围内无 RCSD 数据的候选不进入新审计表；已人工填写的行，包括 `selected_ids=NULL` 或人工新增行，继续保留。
- 排序优先展示未审计且 Segment 范围内有 RCSD 数据的候选，再按最高优先级 Segment 长度和影响 Segment 数降序；已审计行排后作为保留记录。

## 6. 什么是对

- 每个候选都能追溯到 T05/T06/T10 输入路径和原因字段。
- Segment 影响按唯一 Segment 聚合，长度来自米制投影下的 Segment 几何。
- “未替换 Segment 中 relation 缺口”表与“全 1V1 relation 成功但未替换”表按 Segment 合并后，应等于 T06 Step3 全量 `relation_status != replaced` Segment 集合。
- 三表拆分输出按 Segment 互补：表 1 为所有有效路口均有可消费 1V1 relation；表 2 为所有有效路口均有证据但存在 relation 缺口；表 3 为存在无证据有效路口。三者按 Segment 合并后，应等于 T06 Step3 全量 `relation_status != replaced` Segment 集合。
- 表 2/3 字段完全相同；表 2 是人工审计重点，表 3 通过路口 50m RCSD 查询和 T03/T04 场景提示降低无效审计。
- 表 2/3 Excel 的 `manual_relation_type` 使用下拉选择；`NULL` 作为人工审计标记，表示事实无 RCSD 可关联或数据复杂无法标注。
- QGIS 插件只服务表 2 / 表 3：任务栏按 `target_id` 去重，重复路口仅显示并写入排序后的第一条 Excel 行，后续重复行保留在 Excel 中但不由插件写入。
- QGIS 插件每次编辑只同步 `manual_relation_type / selected_ids / comment`，首次写入前创建 workbook 备份；`selected_ids=NULL` 代表人工确认没有有效关系，`comment` 不自动追加时间戳或来源。
- 人工 Excel 重跑时，三张 Segment 审计表都会被扫描；只有可执行 relation 类型且 `selected_ids` 非空、非 `NULL`、`manual_row_consumable` 非 0 的行会进入 T05。重复 `target_id` 只消费首个可执行行。
- “全 1V1 relation 成功但未替换”表只收录所有语义节点 relation 均已成功且可消费，但 Step3 未 `replaced` 的 Segment；它不混入 relation 缺失候选。
- GPKG 保留明确 CRS，T11 不修补、不裁剪、不重构输入几何。
- 新人工模板不预填人工结论；全量审计表可保留已有人工结论，未填写行保持空值。

## 7. 什么是错

- 把 T11 候选当作人工确认结果。
- 把人工模板直接交给 T06 消费。
- 把 QGIS 插件临时状态当作人工结果事实源，或用最后导出覆盖 Excel。
- 为提高候选数量而改写 T05/T06 上游字段含义。
- 覆盖冻结 baseline 或既有 T10 Case root。
