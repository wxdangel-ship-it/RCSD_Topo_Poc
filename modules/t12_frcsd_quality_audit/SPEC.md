# T12 模块需求：原始 1V1 FRCSD 质量审计

## 1. 模块定位

T12 检查原始 1V1 匹配生成的 FRCSD 是否保留 SWSD 的通行拓扑。SWSD 与该 FRCSD 理论上应通行等价，但这只是待数据验证的质量假设，不能直接变成修复规则。

T12 与 T06 分工明确：T06 继续负责 Segment 替换预检和 F-RCSD 生成；T12 以原始 1V1 FRCSD 为 target，消费 T06 Step2/Step3 结果仅作交叉解释，不改变 T06 行为。

## 2. 业务目标

- 找到两端已锚定且 SWSD 要求通行、但原始 1V1 FRCSD 缺少等价 carrier 的 Segment。
- 用复合路口节点组、实际接入 portal、局部/全图和有向/无向路径证据降低误报。
- 将自动候选与人工复核严格分层，最终只发布已复核确认的质量问题。
- 在 T10 中可选 audit-only 编排，不改变 T06、T11、T09 的既有 handoff。

## 3. 当前范围

### 3.1 正式支持

- 原始 1V1 FRCSD Road/Node 全图或显式切片。
- SWSD Segment 所含道路的必需方向。
- T05 成功锚点、`grouped_rcsdnode_ids`、FRCSD `mainNodeId/subNodeId` 与 RCSDIntersection 真值组。
- 默认 `50m` local corridor 和 portal radius；参数必须进入 manifest。
- `directed_carrier_missing` 与 `required_local_connectivity_missing` 两类确认问题。
- 候选、复核排除、待复核、最终确认和 carrier 空间证据。

### 3.2 当前非目标

- 不修复或改写 FRCSD、SWSD、T05、T06、T09、T11 数据。
- 不把 Source、DriveZone 覆盖率、T06 拒绝原因单独作为质量结论。
- 不自动把候选提升为确认问题。
- 不按对象 ID 建白名单或修复规则。

## 4. 输入与输出

| 类型 | 对象 | 用途 |
|---|---|---|
| 输入 | SWSD Segment/Road/Node | 给出质量要求的方向、几何走廊和 portal。 |
| 输入 | 原始 1V1 FRCSD Road/Node | 被审计 target。 |
| 输入 | T05 anchor audit / RCSDIntersection | 路口锚定、节点组和人工标准路口证据。 |
| 输入 | T06 run root | Step2 失败与 Step3 对比证据，不参与 target 替换。 |
| 可选输入 | DriveZone、Case manifest、review decisions | 参考面、裁剪边界和外部复核。 |
| 输出 | candidates CSV/GPKG、carrier evidence GPKG | 自动候选和可复核证据。 |
| 输出 | confirmed/exclusions/manual CSV，confirmed GPKG | 三类互斥复核结果。 |
| 输出 | manifest/summary/report | 输入指纹、参数、CRS、拓扑、数量、状态和耗时。 |

## 5. 关键业务步骤

1. 预检全部输入路径、字段、CRS、几何有效性和 FRCSD Road endpoint 完整性；禁止 silent fix。
2. 依据 SWSD Segment 内道路图确定必需方向，并用 T05/RCSDIntersection/FRCSD 节点组建立候选 portal。
3. 比较 local/full directed/undirected carrier；路径必须同时满足长度和走廊偏离阈值。
4. 生成自动候选并附带 T06/DriveZone 交叉证据，但不自动确认。
5. 按外部 review contract 发布 confirmed、excluded、manual 三类结果。

## 6. 什么是对

- 起点与终点归并到同一 FRCSD 语义节点时，零长度路径视为可达。
- 复合路口允许正反方向使用不同的有效接入 portal。
- `candidate_count = confirmed + excluded + manual`，三组 candidate ID 互斥。
- 无复核文件时 confirmed 必须为 `0`，全部候选进入 manual。
- 最终结果不含高概率/中概率分类。

## 7. 什么是错

- 只检查单一 base node、固定 30m 门户或只看全图连通性。
- 把附近任意长绕行当作等价 carrier。
- 用 DriveZone 缺口静默否决拓扑异常，或用 Source 字段决定真伪。
- 把 T06 Step3 F-RCSD 冒充原始 1V1 FRCSD target。
- 根据局部样本固化上游字段新语义。

## 8. 当前治理缺口

- 内网完整数据尚需用户在可执行内网环境中运行 T10 full runner；本仓库只提供入口、预检和审计合同。
- 新城市/大范围数据的 portal 与 carrier 参数需要基于复核结果校准，不能由单个 `1026960` 用例直接推广。
