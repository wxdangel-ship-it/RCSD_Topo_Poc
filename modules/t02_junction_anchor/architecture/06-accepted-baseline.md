# 06 Accepted Baseline

## 1. 文档状态
- 状态：`accepted baseline / revised official alignment`
- 说明：
  - 本文档承载当前已确认的 T02 accepted baseline 业务口径。
  - 若实现与本文档冲突，应先视为实现待对齐，不得自行改写 accepted baseline。
  - 若 T01 上游事实、当前实现与本文档之间存在理解分歧，应先说明 T02 文档存在歧义，再由业务拍板。
  - `t02-fix-node-error-2` 与文本证据包是独立支撑入口，不改写 stage1 / stage2 / stage3 主阶段链。
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

说明：
- stage3 已纳入当前正式 baseline。
- 文本证据包与 `t02-fix-node-error-2` 不属于新的业务阶段。
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
- `stage4` 候选口径冻结为：
  - `has_evd = yes`
  - `is_anchor = no`
  - `kind_2 in {8, 16}`
- `kind_2 = 8` 表示 merge（`2 in 1 out`）
- `kind_2 = 16` 表示 diverge（`1 in 2 out`）
- `stage4` 实现采用 stage3 的栅格策略主线，但不依赖 stage3 产物文件
- `RCSDRoad` / `RCSDNode` 不在 `DriveZone` 上必须报异常，不允许 silent fix

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
- 若覆盖失败但输入完整，记 `review_required` 风险，不得 silent fix
- 若 `mainnodeid` 关联不稳定、patch 无法形成主连通域、关键字段缺失或 CRS 无法统一到 `EPSG:3857`，必须报异常

## 6. 阶段一：stage1，DriveZone / has_evd gate

### 6.1 目标
- 回答“该双向 Segment 相关路口是否有道路面资料”。
- 输出代表 node 的 `has_evd` 与 `segment.has_evd`。
- 为 stage2 和 stage3 提供资料前置 gate。

### 6.2 当前业务规则
- 只认 `pair_nodes + junc_nodes` 中出现的目标路口。
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
- `has_evd != yes` 的组不进入 stage2，代表 node `is_anchor = null`。
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

## 10. 阶段四：stage4，diverge / merge virtual polygon

### 10.1 目标
- 处理 `has_evd = yes`、`is_anchor = no` 且 `kind_2 in {8, 16}` 的单个 `mainnodeid`。
- 生成保守虚拟路口面，覆盖目标 `mainnodeid` 对应的 `RCSDNode` seed 与相关 node。

### 10.2 当前业务规则
- `kind_2 = 8` 归因为 merge（`2 in 1 out`）。
- `kind_2 = 16` 归因为 diverge（`1 in 2 out`）。
- stage4 采用 stage3 的栅格策略主线：
  - patch + mask + 连通提取 + 回矢量 + 审计
- stage4 不重写 `nodes.is_anchor`，也不并入统一锚定结果。

### 10.3 当前正式输出语义
- `stage4_virtual_polygon.gpkg`
- `stage4_node_link.json`
- `stage4_rcsdnode_link.json`
- `stage4_audit.json`
- 可选 `stage4_debug/`
- `stage4_status.json`、`stage4_progress.json`、`stage4_perf.json`、`stage4_perf_markers.jsonl` 仍可作为运行态工件输出，但不属于当前 stage4 正式输出契约。

## 10. 当前已落地 / 已固化内容
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

## 11. 当前仍需继续验证 / 修正的内容
- 少量 stage2 `fail1 / fail2 / anchor_reason` 的边界 case 仍需继续回归验证。
- stage3 在特殊主辅路、复合 T 型、复杂 RC 局部组件上的锚定规则仍需继续验证。
- stage3 full-input 的性能优化、共享大图层局部裁剪与输出体积控制仍需继续治理。
- `t02-fix-node-error-2` 当前需要进一步做局部化读取与定点更新，以改善性能与输出体量。
- 文本证据包之外的更完整外部复现闭环仍未纳入当前 baseline。
- 最终唯一锚定决策、概率 / 置信度与正式产线闭环仍未进入当前正式范围。

## 12. 当前推荐对齐原则
- 若 T02 仓库文档与本 accepted baseline 冲突，以本文档为准。
- 若实现与本文档冲突，应先说明文档歧义或实现偏差，再由业务拍板。
- 未经明确允许，不修改已固化的 T02 accepted baseline。
- T01 仍是 T02 的上游事实源之一；后续 T03 等模块消费 T02 结果时，默认以：
  - stage1 / stage2 的 `nodes.gpkg`
  - stage1 的 `segment.gpkg`
  - stage3 的 `virtual_intersection_polygon(s).gpkg`
  - 对应 `summary / audit / log`
  作为标准理解基础。
