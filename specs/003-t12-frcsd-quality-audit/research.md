# Research: T12 FRCSD 质量审计

## 决策 1：被检对象与 T06 证据分离

- **Decision**: 原始 1V1 FRCSD Road/Node 是唯一被检 target；T06 Step2 rejected/probe/failure/problem registry 是候选与解释证据，T06 Step3 输出只作对照。当前兼容流程中 T06 消费 T05 copy-on-write `rcsdroad_out/rcsdnode_out`，因此校验同批次 T05→T06 派生链，不要求它与原始 target 文件指纹相同。
- **Rationale**: T05 会为 junctionization 做 copy-on-write，T06 Step3 还会执行 Segment 替换、保留 SWSD carrier 和拓扑闭合；这些产物都不能代表原始 1V1 FRCSD 事实。用户已明确 1V1 FRCSD 不是当前仓库 Segment 替换结果。
- **Alternatives considered**: 直接审计 T06 Step3 F-RCSD；会混入修复与 source mix，拒绝。

## 决策 2：候选、复核、最终问题三层分离

- **Decision**: 自动阶段只输出 `candidate_pending_review`；复核输入产生 `confirmed_frcsd_quality_issue / excluded_false_positive / manual_review_required`；只有 confirmed 进入最终清单。
- **Rationale**: 当前 35 个候选经原始数据复核后只有 10 个成立。用户要求最终输出经复核后就应是真实质量问题，不再区分高/中概率。
- **Alternatives considered**: 把严格自动规则直接叫“确认问题”；当前 portal/复合路口证据仍可能产生假阳性，拒绝。

## 决策 3：portal 搜索与路口组规则

- **Decision**: portal 搜索半径与局部 corridor 统一为默认 50m；T05 `grouped_rcsdnode_ids`、FRCSD `mainnodeid/subnodeid` 的全部合法组成员都参与 start/end portal，多集合路径搜索分别使用出边/入边资格。
- **Rationale**: `1001716_1010487` 的合法起点距 SWSD portal `32.646m`，旧 30m 半径漏检；`1039488_1039490` 的合法端点是 T07/T05 路口组成员而非 selected main node。50m 与 T06 正式 buffer 口径一致，同时不扩大最终问题判定，只扩大证据搜索。
- **Alternatives considered**: 对两个对象加白名单；违反可推广性和字段管控，拒绝。无限半径搜索；会把远处道路误作 portal，拒绝。

## 决策 4：carrier 等价证据阈值

- **Decision**: 沿用已验证实验的审计阈值：局部 corridor 50m、路径长度比 `<=1.5` 或增量 `<=100m`、最大 corridor 偏离 `<=50m`、采样间距 5m。阈值用于发现/排除候选，不是修复规则。
- **Rationale**: 这组阈值能接纳已核实的复杂 portal carrier，同时保留远距离绕行和方向缺失证据；与 T06 50m corridor 方法论一致。
- **Alternatives considered**: 30m portal；已出现实证漏检。只比较长度；无法排除远距离绕行。只用 DriveZone；参考面存在缺口。

## 决策 5：方向语义复用 T06

- **Decision**: 复用 T06 `parsing`、`NodeCanonicalizer` 和 direction/formway 解释：FRCSD `direction in {0,1,2}` 支持 `snodeid -> enodeid`，`direction in {0,1,3}` 支持反向；SWSD 必需方向从 Segment 内 Road 和 pair portal 推导。
- **Rationale**: 避免 T12 与 T06 对相同字段形成不同语义。Source 字段不参与通行通过/失败判定。
- **Alternatives considered**: T12 自行定义 direction；会形成规则分叉，拒绝。

## 决策 6：RCSDIntersection 真值使用边界

- **Decision**: RCSDIntersection/T07 成功 relation 用于确认路口身份和锚点组合法性；不能把“已锚定”直接等同于“Segment carrier 必然存在”，carrier 仍需原始 FRCSD 路径验证。
- **Rationale**: 用户确认 RCSDIntersection 是人工标准路口；同时 SWSD/FRCSD 拓扑等价仍是待数据验证的质量假设。
- **Alternatives considered**: 只要两端 T07 就自动报错；忽略复合 portal，假阳性风险高。

## 决策 7：T10 stage 位置与兼容性

- **Decision**: T12 位于 `T06 Step3` 后、`T11` 前，为可选 audit-only stage；启用时要求显式 1V1 FRCSD slots，未启用时保持既有 Case/full 流程。
- **Rationale**: 该位置可消费完整 T06 Step2/Step3 证据，又不改变 T11/T09 既有 handoff。
- **Alternatives considered**: 放在 T06 前；缺少 T06 诊断证据。替代 T11；两者审计对象不同。阻断 T09；用户未授权改变现有业务效果。

## 决策 8：正式入口

- **Decision**: 新增一个 root script `scripts/t12_run_frcsd_quality_audit.py` 作为 standalone 正式入口，T10 adapter 调用同一模块 callable；不新增 repo CLI 子命令。
- **Rationale**: 现有 T06/T11 都采用 root script 运行模式；单一薄入口便于内网和 T10 复用，同时避免继续扩大集中式 `cli.py`。
- **Alternatives considered**: 仅 `python -c`；不利于长期可运行与契约治理。新增 CLI 子命令和 root script 两个入口；重复入口，拒绝。

## 决策 9：真实数据与内网验证边界

- **Decision**: 本地实际执行 `E:\TestData\POC_QA\T10\1026960`；内网完整数据只交付可运行入口、预检和审计，不声称已执行。
- **Rationale**: 当前会话无内网执行能力，符合仓库 §7。
- **Alternatives considered**: 用本地裁剪结果推断内网全量性能/准确率；证据范围不足，拒绝。
