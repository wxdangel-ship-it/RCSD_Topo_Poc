# T12 模块需求：原始 1V1 FRCSD 质量审计

## 1. 模块定位

T12 检查原始 1V1 匹配生成的 FRCSD 是否保留 SWSD 的通行拓扑。SWSD 与该 FRCSD 理论上应通行等价，但这只是待数据验证的质量假设，不能直接变成修复规则。

T12 与 T06 分工明确：T06 继续负责 Segment 替换预检和 F-RCSD 生成；T12 以原始 1V1 FRCSD 为 target，消费 T06 Step2/Step3 结果仅作交叉解释，不改变 T06 行为。

## 2. 业务目标

- 找到两端已锚定且 SWSD 要求通行、但原始 1V1 FRCSD 缺少等价 carrier 的 Segment。
- 用复合路口节点组、实际接入 portal、局部/全图和有向/无向路径证据降低误报。
- 将 canonical 宽召回候选与 raw endpoint 正式判定严格分层，自动发布通过标准路口与锚点可信度门禁的高置信质量问题；人工复核仅作可选 QA 覆盖。
- 在 T10 中可选 audit-only 编排，不改变 T06、T11、T09 的既有 handoff。

## 3. 当前范围

### 3.1 正式支持

- 原始 1V1 FRCSD Road/Node 全图或显式切片。
- SWSD Segment 所含道路的必需方向。
- T05 成功锚点、`grouped_rcsdnode_ids`、FRCSD raw Road endpoint、仅用于宽召回的 `mainNodeId/subNodeId`，以及 RCSDIntersection 标准路口面。
- 默认 `50m` local corridor 和 portal radius；参数必须进入 manifest。
- `directed_carrier_missing` 与 `required_local_connectivity_missing` 两类确认问题。
- 候选、自动确认、自动排除、可选复核覆盖和 raw/canonical carrier 空间证据。

### 3.2 当前非目标

- 不修复或改写 FRCSD、SWSD、T05、T06、T09、T11 数据。
- 不把 Source、DriveZone 覆盖率、T06 拒绝原因单独作为质量结论。
- 不把仅由 canonical 节点折叠、邻近任意 portal、Source、DriveZone 或 T06 拒绝原因支持的候选提升为确认问题。
- 不按对象 ID 建白名单或修复规则。

## 4. 输入与输出

| 类型 | 对象 | 用途 |
|---|---|---|
| 输入 | SWSD Segment/Road/Node | 给出质量要求的方向、几何走廊和 portal。 |
| 输入 | 原始 1V1 FRCSD Road/Node | 被审计 target。 |
| 输入 | T05 anchor audit / RCSDIntersection | 路口锚定、节点组和人工标准路口证据。 |
| 输入 | T06 run root | Step2 失败与 Step3 对比证据，不参与 target 替换。 |
| 可选输入 | DriveZone、Case manifest、review decisions | 参考面、裁剪边界和外部 QA 覆盖。 |
| 输出 | candidates CSV/GPKG、carrier evidence GPKG | 自动候选和可复核证据。 |
| 输出 | confirmed/exclusions/manual CSV，confirmed GPKG | 自动决定与可选复核覆盖后的互斥结果；默认自动运行 manual=0。 |
| 输出 | manifest/summary/report | 输入指纹、参数、CRS、拓扑、数量、状态和耗时。 |

## 5. 关键业务步骤

1. 预检全部输入路径、字段、CRS、几何有效性和 FRCSD Road endpoint 完整性；禁止 silent fix。
2. 依据 SWSD Segment 内道路图确定必需方向；canonical 图只做宽召回候选，raw Road endpoint 图负责正式 carrier 判定。
3. T07 使用 T05 显式 group 与对应 RCSDIntersection 面内 raw portal；T03/T04 使用显式 group 与 SWSD 实际接入侧 spatial portal。
4. 比较 raw local/full directed/undirected carrier，并以同 portal 策略下的 canonical directed/undirected 路径区分“方向缺失”和“局部物理连接缺失”；canonical 路径不得覆盖 raw failure verdict。路径必须同时满足长度和走廊偏离阈值。
5. 对具有 T07 标准面信用或 T03/T03 正式锚点信用的 raw carrier 缺失自动 confirmed；等价 carrier 或锚点信用不足自动 excluded。
6. 可选 review contract 可以覆盖自动决定，并完整保留原规则与外部来源。

## 6. 什么是对

- canonical 图中归并到同一 FRCSD 语义节点的零长度路径只能用于候选筛选；正式 verdict 必须在 raw endpoint 图上证明。
- 复合路口允许正反方向使用不同的有效接入 portal。
- `candidate_count = confirmed + excluded + manual`，三组 candidate ID 互斥。
- 无复核文件时也必须自动生成 confirmed/excluded；默认自动运行 manual 必须为 `0`。
- 最终结果不含高概率/中概率分类。

## 7. 什么是错

- 只检查单一 base node、固定 30m 门户、canonical 零成本归并或只看全图连通性。
- 对 T07 使用标准路口面之外的任意 50m 邻近节点作为正式 portal。
- 把附近任意长绕行当作等价 carrier。
- 用 DriveZone 缺口静默否决拓扑异常，或用 Source 字段决定真伪。
- 把 T06 Step3 F-RCSD 冒充原始 1V1 FRCSD target。
- 根据局部样本固化上游字段新语义。

## 8. 当前治理缺口

- 内网完整数据尚需用户在可执行内网环境中运行 T10 full runner；本仓库只提供入口、预检和审计合同。
- 新城市/大范围数据的 portal 与 carrier 参数需要基于 QA 结果校准；本次自动判定结构可推广，但不能把单个 `1026960` 用例直接解释为所有城市参数已充分验证。
