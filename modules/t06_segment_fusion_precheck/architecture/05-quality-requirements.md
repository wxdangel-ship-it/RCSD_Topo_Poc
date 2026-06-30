# 05 质量要求

## 1. 替换正确性

- Step2 只接受 `status=0 / base_id>0` 的 T05 relation。
- `pair_nodes` 是 hard required，`junc_nodes` 是 optional 审计对象。
- buffer 连通分量不能直接作为 RCSDSegment，必须收缩为 pair required semantic nodes 之间的可解释 corridor。
- `replaceable` 必须通过方向、叶子端点、额外 mapped semantic nodes、buffer overlap、视觉连续性和特殊组门控。
- 准确 T05 relation 下 retained-junction 20m 距离 gate 不能作为 hard reject，只能作为 Step2 replacement plan 风险标记并由 Step3 topology audit 验证。
- Step3 只能执行 `t06_segment_replacement_plan.*` 中 `plan_status=ready` 的 action。

## 2. GIS 与拓扑要求

- SWSD geometry 定义 buffer window；RCSD geometry 用于候选选择和 retained 输出。
- `formway` 必须按 bit mask 判断，提前右转为 `formway & 128 != 0`。
- Step3 不重写 SWSD/RCSD 原始 id，通过 `source` 区分。
- F-RCSD Road 的端点必须存在于 F-RCSD Node。
- retained SWSD carrier、topology supplement 和提前右转补丁不能混入正式 RCSD 替换道路清单。
- surface-assisted closure 只能补节点语义或 relation node map，不能新增替换道路。

## 3. 业务边界质量

- 高置信 repair candidate 只允许在当前 Segment 内构造 effective relation 并重新跑 Step2 硬审计；不得回写 T05 relation。
- 高等级 graph-first / adaptive buffer 受限重审不能绕过方向、几何、叶子端点、额外 mapped semantic node 或特殊组硬审计。
- `accepted_non_replaceable` 表示 T06 已确认不可替换且不应继续上游重跑的场景。

## 4. 回归要求

测试应覆盖 Step1 self-pair rejected、junc 脱挂、advance right bit mask、Step2 replacement plan / problem registry、pair anchor formal retry、特殊组门控、Step3 replacement plan 优先、detached carrier 保留、advance right attachment、surface topology audit 和 topology connectivity audit。

## 5. 性能要求

Step2 全量运行需关注 buffer candidate graph、probe、group replacement 和输出写入体量。Step3 需关注 F-RCSD 输出、surface topology postprocess 和 topology connectivity audit 的耗时。性能优化不得改变 replacement plan、problem registry 或 Step3 relation 的业务语义。
