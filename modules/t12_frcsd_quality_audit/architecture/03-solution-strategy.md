# 03 Solution Strategy

## 1. 策略总览

T12 保持既有 Segment 主流程：先用 canonical base-node 图检查必需方向的宽召回疑点，再以 raw Road endpoint 图、标准路口面和实际接入 portal 构造多源多目标最短路，比较局部/全图、有向/无向 carrier。raw failure 依次经过 portal-constrained semantic carrier 与 T07 Road-surface portal carrier 排除检查。对必需方向已经等价的单向 Segment，再反转 portal 检查 raw FRCSD 反向载体，并以 SWSD 全图反向替代路径保守排除。完成对应排除且通过候选种类专属锚点门禁后才自动进入正式问题，外部复核仅作可选 QA 覆盖。

Junction 流程与 Segment 独立：T03 rejected 只提供候选，T12 在原始 FRCSD 中重算 target projection、局部 support ownership、endpoint degree、component 与替代 carrier；T07 Step2 final `fail1/fail2` 稳定失败直接发布，不重新裁决。

## 2. 预检与建图

- 校验文件、字段、CRS、几何和 endpoint；记录输入 SHA-256。
- 复用 T06 的 `NodeCanonicalizer`、ID 解析和 direction 语义，不复用 T06 替换判定；canonical 图用于候选筛选及受限 semantic 排除。
- 主判定另建 raw endpoint 图，不折叠 `mainNodeId/subNodeId`；图边按 Road ID 稳定排序。semantic 排除路径不得为零长度，并记录每个实际 raw endpoint transition。

## 3. Anchor portal 与 carrier

- T05 只将选中 `base_id` 通过 `mainNodeId/subNodeId` 展开同 canonical group 的 anchored raw alias；其它显式 grouped raw node 保留但不递归扩组。这些成员距离只作审计，但每个方向仍独立筛选，start 必须属于 raw local directed graph 的 outgoing node，end 必须属于 incoming node。
- T07 对非 anchored node 只加入与该 SWSD 语义路口唯一关联的 RCSDIntersection 面内 raw node；T03/T04 对非 anchored node 只在 SWSD carrier 端点 `50m` 内查找 spatial raw portal。两类 fallback 同样执行方向角色过滤。
- 路径必须满足长度比例、绝对增量和最大走廊偏离三项阈值。
- 双端唯一 T07 标准面时，可附加 Road-surface portal：有向 Road 几何与对应标准面相交，或 carrier frontier 与锚点组之间存在 anchor→frontier 一跳物理 Road；support Road 必须接触标准面（允许 `1m` 拓扑容差），且 carrier 至少一端实际 Road-surface contact。该层长度比例/附加长度仍是强门禁；其它 surface/portal/alias/corridor 距离只作审计。

## 4. 候选与复核

- raw local directed 失败后，若 canonical local directed 物理 Road 路径通过原长度/增量/走廊阈值，且两端 portal 与内部 alias transition 全部受信，则按 `equivalent_portal_constrained_semantic_carrier` 排除该 raw 假断裂。T07 alias 端点只接受同一唯一标准路口面；非 T07 alias 端点和内部 alias transition 还必须在 `portal_radius_m` 内。
- raw/canonical undirected path 仅用于诊断物理走廊与方向差异；它不得提供当前方向 portal，不得成为等价 basis，也不得覆盖 directed failure。
- anchored canonical membership 不能产生 semantic 零长度 carrier；raw 等价仍必须在 identity node 图上包含实际 Road，并逐边符合 Direction。
- 若上述层仍失败但双端唯一 T07 标准面成立，则在实际有向 Road 图上搜索 Road-surface/anchor-one-hop-frontier 路径；通过方向、物理 Road、surface access 与长度门禁后，按 `equivalent_t07_road_surface_carrier` 排除。距离指标保留到审计，不单独拒绝。
- 完成上述排除后，canonical local directed 仍失败而 canonical local undirected 成功时判为 S01 `segment_required_direction_unavailable`；其它未解决方向判为 S02 `segment_required_connection_missing`。多个失败方向中只要存在明确方向缺失证据，Segment 级类型优先为 S01。
- 至少一端具有唯一 T07 标准面信用，或两端均为正式 T03 anchor 时，允许未解决失败自动 confirmed；其它失败按 `insufficient_anchor_confidence` 排除。
- raw portal 找到等价 carrier 时按 `equivalent_raw_carrier` 排除；生产算法不按对象 ID 特判。
- 单向 Segment 只有在所有必需方向已等价时才检查反向；短 Segment 的 portal 先按两端 SWSD portal 距离做 Voronoi 分侧，双 T07 可补充同 canonical group、`portal_radius_m` 内的实际 raw endpoint。该扩展只选择端点、不增加图边；raw FRCSD 反向路径仍必须连续包含实际 Road 并通过既有长度比例、附加长度和走廊阈值。
- 反向路径第一/最后 Road 必须分别接触反向 source/target T07 标准路口面，允许既有 `1m` 拓扑容差。扣除双端标准面及容差后，区间内每条 raw RCSD Road 按 `20m coverage > 50m coverage > geometry distance` 与全量 Segment 竞争，当前 Segment 必须是唯一最优；其它 Segment 更优或并列均自动排除。
- SWSD 全图存在通过同一几何阈值的反向替代路径时按 `unexpected_reverse_swsd_equivalent` 排除；弱锚点按 `unexpected_reverse_insufficient_high_precision_evidence` 排除；其它 Segment 更强覆盖、归属歧义或锚点区间未证明分别排除。只有双端唯一 T07 标准面、锚点区间、当前 Segment 唯一归属全部成立时，才按 `unexpected_reverse_raw_carrier_dual_t07_segment_scoped` 自动确认。
- review CSV 严格 join 当前 run/candidate；缺失 review 行保留自动决定，显式行可以覆盖。

## 5. 实现分层

- `inputs.py`：输入、CRS、拓扑和证据派生链。
- `junction_inputs.py`：T03/T07 正式工件发现、完整性、来源身份与指纹。
- `junction_audit.py`：T03 原始 FRCSD 复核与 T07 稳定失败展开。
- `junction_outputs.py`：独立 Junction Point 结果和根因 evidence。
- `carrier_graph.py / anchor_portals.py`：图与门户。
- `semantic_carrier.py`：semantic 物理路径、端点 portal 与内部 alias transition 门禁。
- `surface_portal_carrier.py`：T07 Road-surface access、一跳 frontier、方向路径与距离审计。
- `candidate_audit.py`：候选和空间证据。
- `review_publish.py / outputs.py`：自动 decision、可选复核覆盖和发布。
- `runner.py`：阶段编排与性能审计。

## 6. 性能与观测

canonical/raw 全图各建一次，canonical groups 与 Segment STRtree 也只构建一次；每个候选只查询并构建 50m local graph。anchored alias 展开使用预构建 group，不做逐候选全图扫描。Road-surface fallback 只对已有失败方向且双端 T07 surface 受信时运行，并复用 local graph/surface 索引。每个要求方向已等价的单向 Segment 最多增加一次 FRCSD local 反向查询、一次 SWSD full 反向查询和实际反向路径 Road 的局部 Segment 归属查询。

Junction source 未提供时走空源 fast path，不构建 Junction 索引。提供时 FRCSD Road/Node、SWSD Node lookup 与空间索引只构建一次；T03 只对 rejected 候选查询局部 support，T07 线性展开。summary 分别记录 `junction_input` 与 `junction_audit`，输出时间继续统一记录在 `output_write`。

## 7. Junction 准确率优先决定

- `shared_degree1_terminal_collapse`：仅对正式 eligible 的 class B/not established、无 required RCSDNode、至少两个 target 运行。优先使用 T03 正式 support IDs；缺失时从 target 最近 raw FRCSD Road 的 endpoint 邻域检索局部 ownership carrier。所有 target 必须投影到同一 support terminal endpoint、endpoint support degree=1，且无局部替代 carrier、无无效几何、无正式高置信跨层解释。
- `multi_component_unmatched_support`：仅对 class B/review、无 required RCSDNode 运行。所有 target 必须只解释同一 support component，至少另有一个未解释 component；同时要求 Step6 fragmented-surface reason、cleanup 前 meaningful component 至少 3、`constraint_induced_split=false`，且无局部替代 carrier和高置信跨层解释。
- raw FRCSD endpoint 的全局 incident Road 可以来自其它 Segment；它只进入全局 degree 审计，不自动成为当前 Junction support。support ownership 以明确路口锚定 target 的局部 carrier 为准。
- Step2 `fail1` 每个语义路口发布一条 J03；`fail2` 按共享 RCSDIntersection 的冲突分量逐语义路口发布 J04 并共享 deterministic conflict group。final state、error GPKG 与 summary 不一致时 blocked；Step3 cardinality 导入数恒为 0。
