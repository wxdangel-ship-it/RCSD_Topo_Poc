# 06 Accepted Baseline

## 1. 文档状态
- 状态：`accepted baseline / revised official alignment`
- 说明：
  - 本文档承载当前已确认的 T02 accepted baseline 业务口径。
  - 若实现与本文档冲突，应先视为实现待对齐，不得自行改写 accepted baseline。
  - 若 T01 上游事实、当前实现与本文档之间存在理解分歧，应先说明 T02 文档存在歧义，再由业务拍板。
  - `t02-fix-node-error-2` 与文本证据包是独立支撑入口，不改写 stage1 / stage2 / stage3 主阶段链。
  - 连续分歧 / 合流聚合工具是独立支撑入口，不构成新的业务阶段。
  - stage4 是独立并行成果，不写回 `nodes.is_anchor`，也不并入统一锚定结果。

## 2. 目标
- 在 T01 `segment / nodes` 基础上，完成双向 Segment 相关路口的资料 gate、anchor recognition 与未锚定路口的虚拟路口面锚定。
- 将“是否有道路面资料”“是否已稳定锚定到 RCSDIntersection”“未锚定时如何生成可审计虚拟路口面”拆成清晰阶段。
- 为下游提供稳定的：
  - `nodes.has_evd`
  - `nodes.is_anchor`
  - `nodes.anchor_reason`
  - `segment.has_evd`
  - stage3 虚拟路口面与审计输出
  - stage4 div/merge 虚拟路口面与关联审计输出
- 保持输出可审计、可复现、可 smoke，而不是把异常、歧义与人工复核信息藏进黑箱逻辑。

## 3. 当前正式阶段链
- stage1：`DriveZone / has_evd gate`
- stage2：`anchor recognition / anchor existence`
- stage3：`virtual intersection anchoring`
- stage4：`diverge / merge virtual polygon`
- 独立支撑入口：
  - 单 / 多 `mainnodeid` 文本证据包
  - `t02-fix-node-error-2` 离线修复工具
  - `t02-aggregate-continuous-divmerge` 连续分歧 / 合流聚合离线工具

说明：
- stage3 已纳入当前正式 baseline。
- 文本证据包、`t02-fix-node-error-2` 与 `t02-aggregate-continuous-divmerge` 不属于新的业务阶段。
- 当前正式阶段链只包含 stage1 / stage2 / stage3 / stage4，不包含最终唯一锚定决策闭环、概率阶段或正式产线级全量治理闭环。

## 4. 当前有效输入

### 4.1 stage1 / stage2 官方输入
- `segment.gpkg`
- `nodes.gpkg`
- `DriveZone.gpkg`
- `RCSDIntersection.gpkg`（stage2）

### 4.2 stage3 官方输入
- `case-package` 模式：
  - `nodes.gpkg`
  - `roads.gpkg`
  - `DriveZone.gpkg`
  - `RCSDRoad.gpkg`
  - `RCSDNode.gpkg`
  - `mainnodeid`
- `full-input` 模式：
  - `nodes.gpkg`
  - `roads.gpkg`
  - `DriveZone.gpkg`
  - `RCSDRoad.gpkg`
  - `RCSDNode.gpkg`
  - `mainnodeid`（可选）

### 4.3 stage4 官方输入

- `nodes.gpkg`
- `roads.gpkg`
- `DriveZone.gpkg`
- `RCSDRoad.gpkg`
- `RCSDNode.gpkg`
- `mainnodeid`

### 4.3 独立支撑工具输入
- `t02-fix-node-error-2`：
  - `node_error_2.gpkg`
  - `nodes.gpkg`
  - `roads.gpkg`
  - `RCSDIntersection.gpkg`
- 文本证据包：
  - `nodes.gpkg`
  - `roads.gpkg`
  - `DriveZone.gpkg`
  - `RCSDRoad.gpkg`
  - `RCSDNode.gpkg`
  - `mainnodeid`（单个或多个）

### 4.4 当前输入兼容口径
- 输入兼容 `GeoPackage(.gpkg)`、`GeoJSON` 与 `Shapefile`。
- 历史 `.gpkt` 只保留兼容读取，不作为正式输出格式。
- 若同名 `.gpkg` 与 `.geojson` 同时存在，默认优先读取 `GeoPackage`。
- 所有空间判定必须在统一 CRS 下完成；stage3 `full-input` 不允许用硬编码 CRS override 掩盖 layer / CRS 问题。

## 4A. 数据源特性与精度约束

- 当前 T02 消费两组道路数据源：
  - **SWSD（`nodes` / `roads`）**：覆盖性高，但精度有误差且工艺有差异；与道路面（`DriveZone`）和导流带（`DivStripZone`）存在偏差，SWSD node 点位与真实的道路分歧 / 合流位置最大可偏差约 `200m`
  - **RCSD（`RCSDNode` / `RCSDRoad`）**：覆盖性差，但精度高，与道路面和导流带套合较好；RCSD node 与真实路口位置差距不超过 `20m`
- 这一特性决定了 stage3 / stage4 的核心策略：
  - SWSD `nodes` 只作为 seed 和候选入口，不能替代真实事件定位
  - RCSD 不是无条件第一硬约束
  - 只有在对应事实路口存在对应 RCSD 挂接时，RCSD 覆盖 / 容差才构成条件性硬约束
  - 若事实路口缺失对应 RCSD 挂接，不以 RCSD 未覆盖作为失败条件
  - 路口面可以不包含 SWSD 路口点位
  - 对于存在挂接的事实路口，stage3 / stage4 必须保护对应的 `RCSDNode`

## 5. 当前业务输入约束

### 5.1 stage1 / stage2 输入约束
- `segment` 与 `nodes` 必须来自同一轮、可追溯的 T01 成果。
- `segment` 当前至少需具备：
  - `id`
  - `pair_nodes`
  - `junc_nodes`
  - `s_grade` 或 `sgrade`
- `nodes` 当前至少需具备：
  - `id`
  - `mainnodeid`
  - geometry
- `DriveZone` 与 `RCSDIntersection` 必须具备可用于“落入或边界接触”判定的面几何。
- `nodes / DriveZone / RCSDIntersection` 在空间判定前统一到 `EPSG:3857`。

### 5.2 stage3 输入约束
- `nodes` 必须包含：
  - `id`
  - `mainnodeid`
  - `has_evd`
  - `is_anchor`
  - `kind_2`
  - `grade_2`
- `roads / RCSDRoad` 当前正式依赖：
  - `id`
  - `snodeid`
  - `enodeid`
  - `direction`
- `RCSDNode` 当前正式依赖：
  - `id`
  - `mainnodeid`
- `case-package` 是 stage3 baseline regression 入口，不允许回退。
- `full-input` 是 stage3 完整数据 baseline 入口，统一承接：
  - 完整数据 + 指定 `mainnodeid`
  - 完整数据 + 自动识别“有资料但未锚定”的路口

### 5.3 stage4 输入约束

- `nodes` 必须包含：
  - `id`
  - `mainnodeid`
  - `has_evd`
  - `is_anchor`
  - `kind` 或 `kind_2`
  - `grade_2`
- `roads / RCSDRoad` 当前正式依赖：
  - `id`
  - `snodeid`
  - `enodeid`
  - `direction`
- `RCSDNode` 当前正式依赖：
  - `id`
  - `mainnodeid`
- `stage4` 候选口径冻结为：
  - `has_evd = yes`
  - `is_anchor = no`
  - 简单 div/merge 候选
  - 连续分歧 / 合流聚合后的 complex 128 主节点
- `kind` 与 `kind_2` 在 stage4 候选识别语义上等价：
  - `kind = 8` 或 `kind_2 = 8` 表示 merge（`2 in 1 out`）
  - `kind = 16` 或 `kind_2 = 16` 表示 diverge（`1 in 2 out`）
  - `kind / kind_2 = 128` 仅在“连续分歧 / 合流聚合后的 complex 主节点”语义下进入 stage4
- `stage4` 实现采用 stage3 的栅格策略主线，但不依赖 stage3 产物文件
- `RCSDRoad` / `RCSDNode` 约束在 stage4 中是条件性硬约束：
  - 只有在对应事实路口存在对应 RCSD 挂接时，RCSD 覆盖 / 容差才构成硬约束
  - 对当前事件直接相关且被纳入解释范围的 RCSD，若超出 `DriveZone`，必须显式失败并留下审计
  - 若事实路口缺失对应 RCSD 挂接，不以 RCSD 未覆盖作为单独失败条件

### 5.3 语义字段约束
- T02 当前正式业务字段为：
  - `has_evd`
  - `is_anchor`
  - `anchor_reason`
- `has_evd` 业务值域冻结为：
  - `yes`
  - `no`
  - `null`
- `is_anchor` 业务值域冻结为：
  - `yes`
  - `no`
  - `fail1`
  - `fail2`
  - `null`
- `anchor_reason` 当前最小值域冻结为：
  - `roundabout`
  - `t`
  - `null`
- `has_evd / is_anchor / anchor_reason` 只对代表 node 写值；非代表 node 保持 `null`。

### 5.4 stage4 语义约束

- stage4 是并行独立成果，不写回 `nodes.is_anchor`
- stage4 的“前后区域范围”先按保守虚拟面处理：
  - 事件核心区
  - 选定分支组前后臂区
- 主 `RCSDNode` 不再被解释为无条件精确 seed：
  - `kind_2 = 16` 时，允许位于分歧前主干 `<=20m`
  - `kind_2 = 8` 时，允许位于合流后主干 `<=20m`
  - 超窗、方向错误或明显 off-trunk 时，不得记为 `accepted/stable`
- 若覆盖失败但输入完整，记 `review_required` 风险，不得 silent fix
- 若 `mainnodeid` 关联不稳定、patch 无法形成主连通域、关键字段缺失或 CRS 无法统一到 `EPSG:3857`，必须报异常

## 6. 阶段一：stage1，DriveZone / has_evd gate

### 6.1 目标
- 回答“该双向 Segment 相关路口是否有道路面资料”。
- 输出代表 node 的 `has_evd` 与 `segment.has_evd`。
- 为 stage2 和 stage3 提供资料前置 gate。

### 6.2 当前业务规则
- 正式候选边界改为：
  - `semantic_junction_set`：从 `nodes` 全表按 `mainnodeid` 组和 singleton fallback 组装出的语义路口集合；组内存在 `kind_2` 非空且不为 `0` 的 node 即纳入
  - `segment_referenced_junction_set`：`pair_nodes + junc_nodes` 去重后的 legacy 目标路口集合
  - `stage1_candidate_junction_set = semantic_junction_set ∪ segment_referenced_junction_set`
- 单 `segment` 内先解析、再去重，不按 `segment-路口` 重复计数。
- 语义路口组装规则：
  1. 先查 `mainnodeid = J`
  2. 若不存在，再查 `mainnodeid = NULL 且 id = J`
- 若 `mainnodeid = J` 成组，则组内 `id = J` 的 node 为代表 node。
- 若代表 node 缺失，记 `representative_node_missing`，不允许 fallback。
- 若任一组内 node 落入或接触 `DriveZone` 边界，则该组代表 node `has_evd = yes`。
- 若组内所有 node 均未命中 `DriveZone`，则该组代表 node `has_evd = no`。
- 路口组不存在时，记 `junction_nodes_not_found`，业务结果按 `has_evd = no`。
- 若 `segment` 没有目标路口，则：
  - `segment.has_evd = no`
  - `reason = no_target_junctions`
- 只有去重后的全部目标路口都为 `yes`，才记 `segment.has_evd = yes`。
- `summary_by_s_grade` 继续只保留 segment 视图。
- `summary_by_kind_grade` 改按 `stage1_candidate_junction_set` 统计。

### 6.3 stage1 当前正式输出语义
- `nodes.gpkg`：继承输入 `nodes` 并新增 `has_evd`
- `segment.gpkg`：继承输入 `segment` 并新增 `has_evd`
- `t02_stage1_summary.json`：
  - 按 `0-0双 / 0-1双 / 0-2双` 分桶
  - 补充 `all__d_sgrade`
  - 补充 `summary_by_kind_grade`
- `t02_stage1_audit.csv/json`
- `t02_stage1.log`
- `t02_stage1_progress.json`
- `t02_stage1_perf.json`
- `t02_stage1_perf_markers.jsonl`

## 7. 阶段二：stage2，anchor recognition / anchor existence

### 7.1 目标
- 只处理 `has_evd = yes` 的路口组。
- 回答“该路口是否已经稳定锚定到 `RCSDIntersection`”。
- 区分正常命中、未命中、同组多面冲突与一面多组冲突。

### 7.2 当前业务规则
- 正式候选边界改为：
  - `stage2_candidate_junction_set = semantic_junction_set ∪ segment_referenced_junction_set`
  - 其中仅 `has_evd = yes` 的组进入 stage2 主判定域
- `has_evd != yes` 的组不进入 stage2，代表 node `is_anchor = null`。
- `kind_2 in {8, 16}` 的组同样进入 stage2 `RCSDIntersection` 锚定主判定：
  - 若满足 stage2 锚定标准，同样可记 `is_anchor = yes`
  - 仅当最终判为 `is_anchor = no` 时，才继续进入 stage4 div/merge
- 若目标组任一 node 落入或接触任一 `RCSDIntersection` 面，则该组进入命中态，但仍需继续检查 `fail1 / fail2`。
- 若组内所有 node 均未落入任何 `RCSDIntersection` 面，则代表 node `is_anchor = no`。
- 单节点组若落入多个 `RCSDIntersection` 面：
  - 代表 node `is_anchor = yes`
  - `anchor_reason = null`
  - 不输出 `node_error_1`
- `kind_2 = 64` 且组内所有 node 均落入任意 `RCSDIntersection` 面：
  - 代表 node `is_anchor = yes`
  - `anchor_reason = roundabout`
  - 不输出 `node_error_1`
- `kind_2 = 2048` 且组内所有 node 均落入任意 `RCSDIntersection` 面：
  - 代表 node `is_anchor = yes`
  - `anchor_reason = t`
  - 不输出 `node_error_1`
- 对未命中上述豁免规则的组，若同一组 node 落入两个不同的 `RCSDIntersection` 面：
  - 代表 node `is_anchor = fail1`
  - 输出 `node_error_1`
- 用 `RCSDIntersection` 反向包含选择路口 node 时：
  - 若一个面对应不止一组 node，则先忽视代表 node `kind_2 = 1` 的组
  - 过滤后若剩余组数大于 `1`，这些组代表 node `is_anchor = fail2`
  - 同时输出 `node_error_2`
  - 过滤后若剩余组数仅为 `1`，该面不再对该组触发 `fail2`
- 优先级冻结为：
  - `fail2 > fail1`
  - 若同一组同时命中新豁免规则与 `node_error_2`，最终仍记 `fail2`
  - 被 `fail2` 覆盖时，`anchor_reason = null`

### 7.3 stage2 当前正式输出语义
- `nodes.gpkg`：继承 stage1 输出 `nodes` 并新增/刷新：
  - `is_anchor`
  - `anchor_reason`
- `node_error_1.gpkg` 与对应审计输出
- `node_error_2.gpkg` 与对应审计输出
- `t02_stage2_summary.json`：
  - `anchor_summary_by_s_grade`
  - `anchor_summary_by_kind_grade`
  - `anchor_summary_by_s_grade` 保持 segment 视图
  - `anchor_summary_by_kind_grade` 改按 `stage2_candidate_junction_set` 统计
- `t02_stage2_audit.json`
- `t02_stage2_perf.json`

## 8. 阶段三：stage3，virtual intersection anchoring

### 8.1 目标
- 只处理“有资料但未稳定锚定”的路口。
- 回答“能否构造合理的虚拟路口面，并把它锚定到 own-group nodes / RCSDNode / RCSDRoad 局部组件”。
- 保证结果可审计、可 render、可做单 case 复核或批次汇总。

### 8.2 stage3 当前候选口径
- 代表 node 必须先满足：
  - `has_evd = yes`
  - `kind_2 in {4, 2048}`
- 正式非 `review_mode` 下，当前默认目标为：
  - `is_anchor = no`
- `case-package` 模式只处理单个 `mainnodeid`。
- `full-input` 模式：
  - 传 `mainnodeid` 时执行单点验证
  - 不传 `mainnodeid` 时自动识别候选并批量处理
  - 支持 `max_cases / workers`

### 8.3 stage3 当前业务规则
- polygon 必须先满足 own-group nodes `must-cover`。
- Step3 当前冻结为规则 A / B / C / D / E / F / G / H：
  - A / B / C：对相邻语义路口入口、同面无关对象、以及其他语义路口内部 node 分别构造 `1m` 级负向掩膜
  - D：当前语义路口候选空间只能在道路面内沿合法方向增长；若某个方向上不存在更早的语义边界或 foreign 边界，则该方向单向最大增长距离不超过 `50m`
  - E：`kind_2 = 2048 / single_sided_t_mouth` 不得进入对向 Road、对向语义 Node、对向 lane、或对向主路 corridor
  - F：若某个方向只能依赖 cleanup / trim 才能不越界，则该方向的 Step3 候选空间不成立
  - G：任何长度放大都只能排在上述硬排除之后且在 Step3 候选空间已自成立后才允许讨论
  - H：旧的 `10m` 保守外扩口径取消；统一采用“无更早边界时单向 `50m`”
- Step3 候选空间必须先自成立；若某个方向只能依赖 cleanup / trim 才能不越界，则该方向的 Step3 候选空间不成立。
- polygon-support 与最终 RC association 可以解耦，但都必须围绕同一局部路口组件。
- 若 RC 不存在与 roads 同方向的有效局部分支，不得拿其他横向或直行 RC 替代。
- 满足不了 own-group nodes 与局部 RC 支撑一致性时，应明确失败或风险，不得 silent fix。
- `review_mode` 只用于人工复核：
  - 可绕过 anchor gate
  - 可将 RC outside DriveZone 从 hard fail 改成风险记录 + 软排除
  - 不改变正式 baseline 契约边界

### 8.4 stage3 当前正式输出语义
- 单 case 输出：
  - `virtual_intersection_polygon.gpkg`
  - `branch_evidence.json/gpkg`
  - `associated_rcsdroad.gpkg` 及审计
  - `associated_rcsdnode.gpkg` 及审计
  - `t02_virtual_intersection_poc_status.json`
  - `t02_virtual_intersection_poc_audit.csv/json`
  - `t02_virtual_intersection_poc_perf.json`
- full-input 批次输出：
  - `preflight.json`
  - `summary.json`
  - `perf_summary.json`
  - `virtual_intersection_polygons.gpkg`
  - `_rendered_maps/`
  - `cases/<mainnodeid>/...`
- 当前典型状态包括：
  - `stable`
  - `surface_only`
  - `weak_branch_support`
  - `ambiguous_rc_match`
  - `no_valid_rc_connection`
  - `node_component_conflict`
  - `anchor_support_conflict`

## 9. 独立支撑入口

### 9.1 文本证据包
- `t02-export-text-bundle / t02-decode-text-bundle` 服务于单 / 多 `mainnodeid` 复核、外部复现和回传。
- 单 case bundle 保持原有 flat 目录结构；多 case bundle 解包后按 `<mainnodeid>/` 展开多个测试用例目录。
- 未显式传入 `--out-dir` 时，多 case bundle 默认解包到当前工作目录。
- 文本证据包允许可选携带 `DivStripZone`，用于 Stage4 并行复核与 case 复现；未显式提供时保持旧 bundle 结构不变。
- 文本证据包不构成新的业务阶段，不改写 stage1 / stage2 / stage3 主流程。
- 导出时继续要求最终文本体积 `<= 300KB`。

### 9.2 node_error_2 离线修复工具
- `t02-fix-node-error-2` 是独立离线修复工具，不挂到 stage 主入口中。
- 它只消费：
  - `node_error_2`
  - `nodes`
  - `roads`
  - `RCSDIntersection`
- 它只输出：
  - `nodes_fix.gpkg`
  - `roads_fix.gpkg`
  - `fix_report.json`
- 当前业务口径：
  - 按 `RCSDIntersection` 反选 `node_error_2` 候选组
  - 忽视 `kind_2 = 1` 组参与候选合并，但仍把它们作为连通阻断候选
  - 若候选组之间通过 `roads` 连通，且路径不穿越其他语义路口，则可增编合并
  - 合并后更新 `nodes_fix`，并删除“组内且面内”的 `roads_fix` 目标 road
- 它不重算 stage2，也不改写 `node_error_2` 的生成逻辑。

### 9.3 连续分歧 / 合流聚合离线工具
- `t02-aggregate-continuous-divmerge` 是独立离线聚合工具，不挂到 stage 主入口中。
- 它只消费：
  - `nodes`
  - `roads`
- 候选只取代表 node 满足：
  - `has_evd = yes`
  - `is_anchor = no`
  - `kind_2 in {8, 16}`
- 连续链识别当前对齐 T04 continuous chain 语义：
  - `diverge -> merge` 距离阈值 `75m`
  - 其他连续 pair 距离阈值 `50m`
  - 仅沿 `direction in {2,3}` 的有效有向 road 搜索
- 聚合输出当前口径：
  - 主 node 取整组 `grade` 最高等级（`1` 最高）
  - 主 node 写 `kind = 128`、`kind_2 = 128`
  - 其余 node 写 `mainnodeid = <mainnodeid>`、`grade = 0`、`kind = 0`、`grade_2 = 0`、`kind_2 = 0`
  - 组内连续链路的 `roads.formway = 2048`
  - 主 node 的 `subnodeid` 写整组 node id 的逗号拼接，包含主 node 自身
- 它只输出：
  - `nodes_fix.gpkg`
  - `roads_fix.gpkg`
  - `continuous_divmerge_report.json`
- `continuous_divmerge_report.json` 同步输出：
  - `counts.complex_junction_count`
  - `complex_mainnodeids`
- CLI 结束时同步打印复杂路口数量和 `mainnodeid` 列表摘要。
- 它不重算 stage1 / stage2 / stage3 / stage4，也不回写统一锚定结果。

## 10. 阶段四：stage4，diverge / merge virtual polygon

### 10.1 当前版本定位
- stage4 当前定位冻结为：
  - 面向分歧 / 合流场景的独立补充阶段
  - 当前不属于统一锚定主流程的一部分
  - 当前不写回 `nodes.is_anchor`
  - 当前不并入统一锚定结果
  - 当前不承担主流程最终唯一锚定闭环
- 上述定位是当前版本定位，不是永久架构边界：
  - 当算法收敛到认可水平后
  - stage4 可与 stage3 合并进入同一锚定流程
  - 并承担对应的锚定信息关联职责
- stage4 的业务主线冻结为：
  - 真实事件优先
  - 不是中心优先
  - SWSD `nodes` 只作为 seed / 候选入口
  - 不能替代真实分歧 / 合流事件定位
- RCSD 当前不是无条件第一硬约束：
  - 只有在对应事实路口存在对应 RCSD 挂接时
  - RCSD 覆盖 / 容差才构成条件性硬约束

### 10.2 当前处理对象与非目标
- stage4 当前处理对象冻结为：
  - 有证据、尚未完成正式锚定
  - 需要按真实分歧 / 合流事件解释的事实路口候选
- 当前正式处理两类对象：
  - 简单 div/merge 候选
  - 连续分歧 / 合流聚合后的 complex 128 主节点
- `kind` 与 `kind_2` 在 stage4 候选识别语义上等价；不得把候选识别写死在单一字段上。
- 普通 div/merge 场景中，`nodeid` 可作为等效 `mainnodeid`；不把“必须存在独立 `mainnodeid`”写成业务前提。
- RCSD 缺失挂接但事实事件存在时，仍属于 stage4 处理对象，不得因为缺少 RCSD 挂接而排除。
- 当前非目标冻结为：
  - 不写回 `nodes.is_anchor`
  - 不并入统一锚定结果
  - 不做最终唯一锚定决策闭环
  - 不做候选生成 / 候选打分
  - 不做概率 / 置信度实现
  - 不做误伤捞回
  - 不做环岛新业务规则
  - 当前可用于审计 / 验证批跑，但不承担正式产线级全量锚定闭环职责

### 10.3 七步正式业务定义
- Step1 候选验证（Candidate Admission）：
  - Step1 是准入 gate，不是正确性 gate
  - 只验证目标对象是否属于 stage4 当前处理范围
  - RCSD 是否存在不影响准入
  - `mainnodeid_out_of_scope` 只表示“不属于 stage4 当前处理范围”
- Step2 高召回事件局部上下文构建（High-recall Local Context）：
  - Step2 不是 patch 全量解释，而是 `DriveZone` 硬边界内的高召回事实事件局部上下文构建
  - diverge：主干向后最多 `50m`，各 branch 臂向前最多 `200m`，不得越过相邻语义路口
  - merge：主干向前最多 `50m`，各 branch 臂向后最多 `200m`，不得越过相邻语义路口
  - Step2 负责组织 `negative exclusion context`，但不完成最终几何排除
  - `DriveZone` 是无条件硬边界；直接相关且被纳入解释范围的 RCSD 若超出 `DriveZone`，直接失败
- Step3 拓扑成骨架（Topology Skeletonization）：
  - Step3 是拓扑成骨架，不是重新分类候选
  - 二度 through node 不打断 branch
  - `chain_context` 是连续 / complex 128 场景下的结构性约束，不是日志附加项
  - Step3 原则上不作为常规业务失败步骤
  - Step3 `allowed space` 不得退化成整片 patch `DriveZone` 直通；主干方向必须有可执行的 frontier / stop condition
  - 当前 case 的 Step3 `allowed space / polygon-support space` 不得进入其他语义路口，也不得纳入其他语义路口向外延伸的 `roads / arms / lane corridor`
  - 当前 case 的 Step3 `allowed space` 不得进入与当前语义/拓扑不连通的对向道路面；该约束按语义/拓扑连通性判定，不按纯几何朝向判定
  - `single_sided_t_mouth` 下，对向 Road / 对向语义 Node / 对向 lane / 对向主路 corridor 一律按硬排除处理
  - 当前 case 的 Step3 候选空间必须先自成立；若某个方向只能依赖 cleanup / trim 才能不越界，则该方向的 Step3 候选空间不成立
  - 任何长度放大、mouth 补长、或竖向补长，都只能排在上述硬排除之后且在 Step3 候选空间已自成立后才允许讨论；不得先放大再依赖 cleanup / trim 补救越界
  - 若某个方向上不存在更早的语义边界或 foreign 边界，则该方向单向最大增长距离不超过 `50m`
  - 旧的 `10m` 保守外扩口径取消，不再作为 Stage3 正式口径
- Step4 事实事件解释层（Fact Event Interpretation）：
  - Step4 是事实事件解释层，不是几何生成层
  - 主输出是供 Step5 / Step6 消费的机器可消费事件解释结果包
  - 证据链最小顺序冻结为：DivStrip 直接事件证据优先 -> `continuous chain / multibranch` 结构约束与裁决 -> `reverse tip` 受控重试 -> 保守 fallback
  - 默认行为是保守降级、显式外露风险，而不是轻易 hard fail
- Step5 事件几何支撑域构建（Geometric Support Domain）：
  - Step5 是事件几何支撑域构建层，不是事件解释层，也不是最终 polygon 层
  - span 必须落在 Step2 召回上限之内，并根据 Step4 结果进一步收敛
  - Step5 正式承担负向排除对象的几何约束落地职责
  - “近似垂直横截面”是正式几何构造要求
- Step6 最终 polygon 组装（Polygon Assembly）：
  - Step6 是最终 polygon 组装层，不再回头解释事件
  - 目标是收敛到一个主 polygon，不输出多候选几何
  - Step6 不直接做 acceptance，只产出几何成形状态和几何风险信号
- Step7 最终业务验收与结果发布（Final Acceptance & Publishing）：
  - Step7 是最终业务验收与结果发布层
  - 只有在对应事实路口存在对应 RCSD 挂接时，才必须满足 RCSD 覆盖 / 容差
  - 三态冻结为：`accepted / review_required / rejected`
  - 三种状态都应尽量落完整独立结果包

### 10.4 审计、目视复核与成果字段
- stage4 正式复用 Stage3 的双线并行成果审计方案：
  - 机器审计
  - 人工目视审计
- 目视审计结果定义冻结为：
  - `V1 认可成功`
  - `V2 业务正确但几何待修`
  - `V3 漏包 required`
  - `V4 误包 foreign`
  - `V5 明确失败`
- 正式映射冻结为：
  - `V1 -> accepted`
  - `V2 -> review_required`
  - `V3 / V4 / V5 -> rejected`
- Stage4 PNG 目视样式正式复用 Stage3 三态样式契约：
  - `accepted`：正常成功图样式
  - `review_required`：浅琥珀 / 橙黄色系风险样式，并带 `REVIEW / 待复核`
  - `rejected` 或 `success = false`：淡红 / 深红失败样式，并带 `REJECTED / 失败`
  - 非成功图不得只依赖细边框、轻微色差或小角标
- Stage4 最终成果路口面字段冻结为：
  - 必带 `mainnodeid`、`kind`
  - geometry 统一为 `EPSG:3857`
  - polygon 图层稳定承载 `divstrip_present / divstrip_nearby / divstrip_component_count / divstrip_component_selected / evidence_source / event_position_source / event_tip_s_m / event_span_start_m / event_span_end_m / semantic_prev_boundary_offset_m / semantic_next_boundary_offset_m / trunk_branch_id / rcsdnode_tolerance_rule / rcsdnode_tolerance_applied / rcsdnode_coverage_mode / rcsdnode_offset_m / rcsdnode_lateral_dist_m`
  - 建议同步固化 `acceptance_class / acceptance_reason`
  - 不得只把这些信息散落在 JSON 中

### 10.5 当前阶段性边界与未来合并方向
- stage4 当前是独立补充阶段，不承担统一锚定结果写回责任。
- 当前 accepted baseline 只冻结 Stage4 的业务定义、审计口径、目视复核口径和输出字段规则，不把当前实现细节直接冻结成业务规则。
- 后续当算法收敛到认可水平后，stage4 可与 stage3 合并进入同一锚定流程，并承担相应的锚定信息关联职责。

## 11. 当前已落地 / 已固化内容
- stage1 `DriveZone / has_evd gate` 已正式落地。
- stage2 `anchor recognition / anchor existence` 已正式落地。
- stage2 的 `is_anchor = yes / no / fail1 / fail2 / null` 已冻结。
- stage2 的 `anchor_reason = roundabout / t / null` 已冻结。
- 单节点多面命中、`kind_2 = 64` 全组命中、`kind_2 = 2048` 全组命中的 stage2 豁免已固化。
- `node_error_2` 在反向包含时先过滤代表 node `kind_2 = 1` 的组已固化。
- stage3 `virtual intersection anchoring` 已纳入当前 baseline。
- `t02-virtual-intersection-poc` 已统一承接 `case-package` 与 `full-input`。
- full-input 已支持统一汇总 `virtual_intersection_polygons.gpkg` 与 `_rendered_maps/`。
- 文本证据包已明确为 stage3 支撑工具，不属于新的业务阶段。
- `t02-fix-node-error-2` 已明确为独立离线修复工具，不纳入 stage 主流程。
- `t02-aggregate-continuous-divmerge` 已明确为独立离线聚合工具，不纳入 stage 主流程。

## 12. 当前仍需继续验证 / 修正的内容
- 少量 stage2 `fail1 / fail2 / anchor_reason` 的边界 case 仍需继续回归验证。
- stage3 在特殊主辅路、复合 T 型、复杂 RC 局部组件上的锚定规则仍需继续验证。
- stage3 full-input 的性能优化、共享大图层局部裁剪与输出体积控制仍需继续治理。
- `t02-fix-node-error-2` 当前需要进一步做局部化读取与定点更新，以改善性能与输出体量。
- 文本证据包之外的更完整外部复现闭环仍未纳入当前 baseline。
- 最终唯一锚定决策、概率 / 置信度与正式产线闭环仍未进入当前正式范围。

## 13. 当前推荐对齐原则
- 若 T02 仓库文档与本 accepted baseline 冲突，以本文档为准。
- 若实现与本文档冲突，应先说明文档歧义或实现偏差，再由业务拍板。
- 未经明确允许，不修改已固化的 T02 accepted baseline。
- T01 仍是 T02 的上游事实源之一；后续 T03 等模块消费 T02 结果时，默认以：
  - stage1 / stage2 的 `nodes.gpkg`
  - stage1 的 `segment.gpkg`
  - stage3 的 `virtual_intersection_polygon(s).gpkg`
  - 对应 `summary / audit / log`
  作为标准理解基础。
