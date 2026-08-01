# 05 Quality Requirements

## 1. 业务正确性

- SWSD 必需方向、FRCSD direction 和 portal 角色必须可解释。只允许选中 `base_id` mainNode 的 canonical raw alias group 提供扩展 raw portal membership；其它显式 grouped raw node 不递归扩组。source 必须有符合当前方向的 outgoing Road，target 必须有 incoming Road，且等价 carrier 必须在 raw identity 图包含实际 Road；无向邻接或 canonical 零成本折叠不得替代有向资格或 carrier。
- 单向 Segment 的反向只由已确认的必需方向反转得到；短 Segment 两端 portal 不得重叠代表同一 raw node。双 T07 canonical endpoint 扩展必须同时满足同 anchor canonical group、`portal_radius_m` 和正确 Voronoi 侧，且只选择端点、不补边。正式反向问题必须有连续 FRCSD raw 物理 Road 路径、无 SWSD 等价反向替代路径、双端唯一 T07 标准面、第一/最后 Road 在 `1m` 容差内接触对应标准面，且扣除两端标准面后的每条 Road 均按 `20m/50m coverage + distance` 唯一归属于当前 Segment。其它 Segment 更强覆盖或并列不得自动确认；T03/T03 等弱锚点不得自动确认。
- 复合路口 canonical 节点组与 raw endpoint 物理通行必须分层；anchored alias 距离只作审计，非 anchored spatial/标准面 fallback 不放宽。既有 portal-constrained semantic 层继续拒绝非 anchored 标准面外 T07 alias 和超出 portal radius 的内部 alias；双端唯一 T07 标准面可由独立 Road-surface 层使用 Road 相交或 anchor→frontier 一跳 surface support Road 排除 node-portal 假断裂，support Road 使用 `1m` 拓扑容差且 carrier 至少一端必须实际接触标准面，其它距离指标仅作审计。两层都不能单独确认问题。
- DriveZone 与 T06 只作证据，不能静默改变 verdict。
- T03 rejected 只形成候选。正式 confirmed 必须在原始 1V1 FRCSD 重算 support ownership、target projection、endpoint/component 和局部替代 carrier，并满足 `shared_degree1_terminal_collapse` 或 `multi_component_unmatched_support` 的完整强门禁。
- T07 Step2 final `fail1/fail2` 分别发布 J03/J04；`fail2 > fail1`，J04 按受影响 Junction 逐 Point 输出并共享 conflict group。Step3 relation cardinality 不进入 candidate。
- 距离只用于 `6m` endpoint 投影容差、`50m` 局部 carrier 查询和审计，不得单独形成 Junction verdict。

## 2. GIS 与拓扑

- CRS 必须存在；距离计算使用 metre-based projected CRS。
- 无效 Segment 主输入几何、缺失 endpoint 和错误批次证据必须阻断；无效 DriveZone 不修复，只使相关 Junction 候选保守排除并留痕。
- 不执行 geometry repair、snap、endpoint 补点或其它 silent fix。
- Road-surface contact/stop 只作判定与审计语义，不截断或改写 Road 几何。
- 反向归属只对临时扣除路口面后的派生几何计算，不写回或裁剪输入 Road。

## 3. Decision、Review 与 formal

- 无复核时也必须自动产生 confirmed/excluded，默认 manual=0。
- confirmed/excluded/manual 三组互斥且计数守恒；manual 只允许由显式外部 override 产生。
- Junction candidate/confirmed/excluded 独立互斥且计数守恒；Junction 本轮不接受 Segment review CSV 覆盖。
- Segment 正式几何保持 T01 Segment 线几何族（`LineString/MultiLineString`），Junction 正式几何必须是 SWSD 代表路口 Point，根因 Road/endpoint/projection/conflict link 只进入 evidence。
- 禁止高/中概率正式分类。

## 4. 观测与性能

- 每次运行留下 manifest、summary、日志、空间证据和分阶段耗时。
- 完整数据性能必须在实际内网环境验证；本地 Case 结果不能替代全量结论。
- 未提供 Junction source 的旧调用必须走 fast path，不能改变 Segment 数量、ID/type 或产生可观测的 Junction 主判定开销。

## 5. 治理

- 入口、生命周期、项目/T10/T12 源事实和实现保持一致。
- 生产代码不硬编码 Case/Segment/Road/Node ID。
