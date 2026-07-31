# T12 模块需求：原始 1V1 FRCSD Segment 与 Junction 质量审计

## 1. 模块定位

T12 检查原始 1V1 匹配生成的 FRCSD 是否保留 SWSD 的通行拓扑，并把上游稳定失败转化为可审计的 Junction 质量问题。SWSD 与该 FRCSD 理论上应通行等价，但这只是待数据验证的质量假设，不能直接变成修复规则。

T12 与 T06 分工明确：T06 继续负责 Segment 替换预检和 F-RCSD 生成；T12 以原始 1V1 FRCSD 为 target，消费 T06 Step2/Step3 结果仅作交叉解释，不改变 T06 行为。T03 rejected 只提供 Junction 候选，T12 必须用原始 FRCSD 重新验证；T07 Step3 已稳定识别的 1:N/N:1 关系基数失败直接发布，不修改或重判 T07。

## 2. 业务目标

- 找到两端已锚定且 SWSD 要求通行、但原始 1V1 FRCSD 缺少等价 carrier 的 Segment。
- 找到 SWSD 仅要求单向、要求方向已等价，且原始 1V1 FRCSD 在当前 Segment 明确双端路口锚点之间还存在唯一归属于当前 Segment 的几何等价反向 carrier。
- 从正式 T03 rejected 审计链中准确率优先确认路口所需拓扑缺失或现实变化/精度差异，并保留原始 FRCSD support、target projection、endpoint degree 和 component 根因。
- 将 T07 `one_target_to_many_base` 与 `many_target_to_one_base` 稳定失败直接发布为 Junction 关系基数问题；`duplicate_target_rows` 只计入 ignored 审计。
- 用复合路口节点组、实际接入 portal、Road-surface、局部/全图和有向/无向路径证据降低误报。
- 将 canonical 宽召回候选、raw endpoint 主判定、portal-constrained semantic 与 T07 Road-surface 误报排除严格分层，自动发布通过标准路口与锚点可信度门禁的高置信质量问题；人工复核仅作可选 QA 覆盖。
- 在 T10 中可选 audit-only 编排，不改变 T06、T11、T09 的既有 handoff。

## 3. 当前范围

### 3.1 正式支持

- 原始 1V1 FRCSD Road/Node 全图或显式切片。
- SWSD Segment 所含道路的必需方向，以及单向 Segment 的相反方向。
- T05 成功锚点、`grouped_rcsdnode_ids`、FRCSD raw Road endpoint、用于已锚定 raw alias group、宽召回及受限误报排除的 `mainNodeId/subNodeId`，以及 RCSDIntersection 标准路口面。
- 默认 `50m` local corridor 和 portal radius；参数必须进入 manifest。
- `directed_carrier_missing`、`required_local_connectivity_missing` 与 `unexpected_reverse_carrier` 三类确认问题；反向问题必须附带锚点区间和跨 Segment 唯一归属证据。
- `junction_required_topology_missing`、`junction_reality_or_precision_gap` 与 `junction_relation_cardinality_mismatch` 三类 Junction 确认问题。
- T03 Junction 候选必须满足正式 eligibility：`has_evd=yes`、`is_anchor=no`、`kind_2 in {4,2048}`，并具有完整 Step3/association/Step6/Step7 rejected 审计链。
- T03 准确率优先规则只确认 `shared_degree1_terminal_collapse` 与 `multi_component_unmatched_support`；`6m` endpoint tolerance 与 `50m` local Junction scope 必须进入 manifest，距离本身只作检索或审计，不能单独形成结论。
- T07 只消费正式 `relation_cardinality_errors.csv/json`；N:1 按受影响 SWSD Junction 逐 Point 输出并共享 `conflict_group_id`。
- 候选、自动确认、自动排除、可选复核覆盖，以及 raw/canonical/portal-constrained semantic/T07 Road-surface/FRCSD 反向/SWSD 反向替代 carrier 空间证据。
- Segment LineString 与 Junction Point 独立发布、独立计数守恒；Junction support Road、endpoint、projection 和冲突关系进入独立 evidence GPKG。

### 3.2 当前非目标

- 不修复或改写 FRCSD、SWSD、T05、T06、T09、T11 数据。
- 不修改 T03/T07 的锚定、匹配、接口或算法，不把 T03 rejected 本身直接当作质量错误。
- 不把 Source、DriveZone 覆盖率、T06 拒绝原因单独作为质量结论。
- 不把 canonical 节点折叠、邻近任意 portal、Source、DriveZone 或 T06 拒绝原因支持的候选提升为确认问题；canonical 只可在受信端点、物理 Road 路径和 alias 间距门禁全部通过时排除 raw 假断裂。
- 不按对象 ID 建白名单或修复规则。

## 4. 输入与输出

| 类型 | 对象 | 用途 |
|---|---|---|
| 输入 | SWSD Segment/Road/Node | 给出质量要求的方向、几何走廊和 portal。 |
| 输入 | 原始 1V1 FRCSD Road/Node | 被审计 target。 |
| 输入 | T05 anchor audit / RCSDIntersection | 路口锚定、节点组和人工标准路口证据。 |
| 输入 | T06 run root | Step2 失败与 Step3 对比证据，不参与 target 替换。 |
| 可选输入 | T03 run root | 只读取正式 rejected Junction 审计链；T12 对原始 FRCSD 重新验证。 |
| 可选输入 | T07 Step3 run root | 只读取正式关系基数失败；1:N/N:1 直接发布。 |
| 可选输入 | DriveZone、Case manifest、review decisions | 参考面、裁剪边界和 Segment 外部 QA 覆盖。 |
| 输出 | candidates CSV/GPKG、carrier evidence GPKG | 自动候选和可复核证据。 |
| 输出 | confirmed/exclusions/manual CSV，confirmed GPKG | 自动决定与可选复核覆盖后的互斥结果；默认自动运行 manual=0。 |
| 输出 | Junction candidates/confirmed/exclusions CSV/GPKG、Junction evidence GPKG | 独立 Point 问题层及根因空间证据；本轮不接受 Segment review CSV 覆盖。 |
| 输出 | manifest/summary/report | 输入指纹、参数、CRS、拓扑、数量、状态和耗时。 |

## 5. 关键业务步骤

1. 预检全部输入路径、字段、CRS、几何有效性和 FRCSD Road endpoint 完整性；禁止 silent fix。
2. 依据 SWSD Segment 内道路图确定必需方向；canonical 图做宽召回候选，raw Road endpoint 图负责主 carrier 判定。1V1/T05 只展开选中 `base_id` mainNode 的 canonical group 到全部 raw subNode/alias；其它显式 grouped raw node 保留但不递归展开其各自 group。每个方向独立过滤：source 只接受当前 raw 有向图存在 outgoing Road 的成员，target 只接受存在 incoming Road 的成员；路径仍在 raw identity endpoint 图跟踪实际 Road，无向图只作方向缺失诊断。
3. anchored canonical alias 的 portal/标准面距离只作审计。T07 非锚定 fallback 只接受对应 RCSDIntersection 面内 raw portal；T03/T04 非锚定 fallback 只接受 SWSD 实际接入侧 `portal_radius_m` 内 spatial portal。
4. 比较 raw local/full directed/undirected carrier。raw local directed 失败后，先检查既有 portal-constrained semantic local directed carrier：路径必须包含至少一条物理 Road 并满足方向、长度、增量和走廊偏离阈值；T07 非 raw 端点必须与 portal 同属唯一 RCSDIntersection 标准面，非 T07 非 raw 端点必须与 portal 同 canonical group 且间距不超过 portal radius；内部每个 alias transition 间距也不得超过 portal radius。
5. 若失败方向两端均为正确且唯一的 T07 标准面锚点，再检查 Road-surface portal carrier：source/target Road 几何与对应标准面相交，或 carrier frontier 可由锚点组一跳物理 Road 明确连接；一跳 support Road 必须存在 anchor→frontier 有向边且与对应标准面相交或满足 `1m` 拓扑容差，整条 carrier 至少一端必须有实际 Road-surface contact。路径必须包含方向正确的物理 Road，并通过长度比例/附加长度门禁。Road-surface gap、SWSD portal gap、内部 alias gap 和走廊距离等其它距离指标仅作审计，不作为该层单独拒绝理由。通过时只能覆盖该方向的 raw/node-portal failure 并自动 excluded。
6. 完成两层误报排除后仍失败、且具有 T07 标准面信用或 T03/T03 正式锚点信用的 candidate 自动 confirmed；raw、portal-constrained semantic 或 T07 Road-surface 等价 carrier，以及锚点信用不足自动 excluded。
7. 对必需方向已全部满足的单向 Segment，先按距两端 SWSD portal 的距离对 raw portal 做 Voronoi 分侧，再反转 source/target portal 检查局部 raw FRCSD 反向载体。双 T07 可补入与 anchor base/group 同 canonical group、位于 `portal_radius_m` 内且属于正确侧的实际 raw endpoint；该扩展只选择端点，不创建 graph edge 或跨越路径内部断点。反向载体必须含实际 Road 并通过既有长度比例、附加长度和走廊偏离门禁。随后在 SWSD 全图搜索相同反向的替代路径，只要通过同一几何门禁即自动排除。
8. 双端唯一 T07 还必须证明反向路径第一/最后 Road 分别接触反向 source/target 标准路口面，允许既有 `1m` Road-surface 拓扑容差。两端标准面及容差内的共享路口几何从归属区间剔除；区间内每条 raw RCSD Road 按正式 `20m coverage > 50m coverage > geometry distance` 排序，必须唯一归属于当前 Segment。其它 Segment 更强覆盖、并列、当前 Segment 缺失或区间内无实际 Road 均自动 excluded，并保留逐 Road 归属证据。
9. 非预期反向 candidate 只有在双端正确且唯一 T07 标准面、锚点区间成立、区间内 Road 唯一归属于当前 Segment时才可自动 confirmed；T03/T03 等弱锚点自动 excluded。DriveZone 不参与该 verdict。
10. 可选 review contract 可以覆盖自动决定，并完整保留原规则与外部来源。
11. 若提供 T03 run root，只读取 Step7 rejected 且完整的正式审计链。T12 优先使用 T03 正式发布的 support Road IDs；缺失时在原始 FRCSD 中从 target 最近 Road 的 endpoint 邻域重算局部 ownership carrier，不把同 endpoint 的其它 Segment Road 自动并入当前 Junction support。
12. `shared_degree1_terminal_collapse` 要求 association class B/not established、无 required RCSDNode、至少两个 target、所有 target 在同一局部 support Road 的同一 terminal endpoint 投影且 support degree=1，同时无原始 FRCSD 替代局部 carrier、无无效几何或正式高置信跨层解释。
13. `multi_component_unmatched_support` 要求 association class B/review、无 required RCSDNode、所有 target 只解释同一 support component、至少一个额外未匹配 component、正式 Step6 fragmented-surface reason、cleanup 前 meaningful component 至少 3、非 constraint split 且无局部替代 carrier或高置信跨层解释。
14. 若提供 T07 Step3 root，`one_target_to_many_base` 每个 target 发布一行；`many_target_to_one_base` 每个 target 发布一行并共享稳定 conflict group；`duplicate_target_rows` 不生成 candidate。

## 6. 什么是对

- canonical 图中归并到同一 FRCSD 语义节点的零长度路径不能作为 carrier。semantic 与 Road-surface 排除证据必须包含物理 Road；Road-surface 层还必须有唯一标准面和显式 surface/frontier access。两者只允许排除 raw 假断裂，不能单独确认问题。
- `direction=0/1` 双向、`2` 为 `snodeId→enodeId`、`3` 为 `enodeId→snodeId`；正反向必须分别沿合法有向 Road 跟踪。反向 Road 只能进入反向 carrier 或无向诊断，不能成为正向 portal/carrier。
- mainNode 锚定只授权选中 `base_id` canonical group 的 raw node 参与扩展 portal 候选；其它显式 grouped raw node 不递归扩组。该 membership 不授权 canonical 零成本通行；正式 raw 等价必须沿这些 raw node 间实际 Road endpoint 链成立。
- 复合路口允许正反方向使用不同的有效接入 portal。
- 反向检查只在要求方向已等价时运行，保持一个 Segment 一个 candidate ID。
- 反向路径位于当前 Segment `50m` local graph 只构成召回，不证明归属；自动确认还必须通过双端 Road-surface 锚点区间和逐 Road 当前 Segment 唯一归属。
- `candidate_count = confirmed + excluded + manual`，三组 candidate ID 互斥。
- `junction_candidate_count = junction_confirmed + junction_excluded`，Junction 与 Segment ID、几何和计数域互不混用。
- 无复核文件时也必须自动生成 confirmed/excluded；默认自动运行 manual 必须为 `0`。
- 未提供 T03/T07 Junction 来源时，旧调用仍成功并发布结构完整的空 Junction 文件，既有 Segment 决定不变。
- 最终结果不含高概率/中概率分类。

## 7. 什么是错

- 只检查单一 base node、固定 30m 门户、canonical 零成本归并、无物理 Road 的 semantic path 或只看全图连通性。
- 对 T07 使用 selected base canonical group 和标准路口面之外的任意邻近节点作为正式 portal；其它 grouped node 不递归扩组。Road-surface 规则只接受 Road 相交或锚点组一跳物理 Road frontier，不能退化为距离接边。
- 把附近任意长绕行当作等价 carrier。
- 未搜索 SWSD 全图反向替代路径就确认 `unexpected_reverse_carrier`，或把 T03/T03 弱锚点自动确认。
- 把当前 Segment `50m` buffer 内的其它 Segment RCSD Road 当作当前 Segment 反向 carrier，或在锚点面接触和唯一归属不成立时自动确认。
- 用 DriveZone 缺口静默否决拓扑异常，或用 Source 字段决定真伪。
- 把 T06 Step3 F-RCSD 冒充原始 1V1 FRCSD target。
- 根据局部样本固化上游字段新语义。
- 直接把 T03 rejected 或 target 到 Road 的最近距离当作 Junction 错误，不复核原始 FRCSD 局部 support ownership、endpoint/component、Direction 与替代 carrier。
- 把 T07 `duplicate_target_rows` 当作 1:N/N:1 Junction 正式错误，或在 T12 中重新裁决 T07 稳定失败。

## 8. 当前治理缺口

- 内网完整数据尚需用户在可执行内网环境中运行 T10 full runner；本仓库只提供入口、预检和审计合同。
- 新城市/大范围数据的 portal 与 carrier 参数需要基于 QA 结果校准；本次自动判定结构可推广，但不能把单个 `1026960` 用例直接解释为所有城市参数已充分验证。
