# 004 - Step2 缺失 pair anchor 侧保持补全

- 日期：2026-06-11
- 模块：T06 Segment fusion precheck
- 变更类型：Step2 高置信 pair anchor 自动重试安全门细化

## 背景

T10 高等级单向 Segment 复测中，`missing_pair_relation` 的失败样本不完全相同：

- 有的样本 T05 relation 已经给出一个 RCSD pair 端点，buffer-only probe 给出唯一候选 corridor，且候选 pair 包含该已知端点。
- 有的样本虽然也有唯一候选 corridor，但候选 pair 不包含 T05 已知端点，无法证明它只是补缺失侧。

原自动重试逻辑直接读取 buffer-only 候选 pair 的顺序。对于单向 Segment，buffer-only 候选 pair 的顺序来自几何端点接近关系，不等价于 SWSDRoad `snodeid / enodeid / direction` 推导出的业务方向。若直接使用候选顺序，可能把 T05 已知端点错误移动到另一侧，导致可通过的缺端补全被安全门挡住，或在放宽安全门后产生错误方向替换。

## 业务逻辑变更

Step2 对 `high_confidence_pair_anchor_candidate` 执行 pair anchor 自动重试时，新增缺失 pair 端点的侧保持补全规则：

1. 仅当 T05 relation 恰好缺失一个 pair 端点、已有一个有效 RCSD pair 端点时适用。
2. buffer-only 候选 pair 必须包含该 T05 已知 RCSD 端点。
3. T06 不采用 buffer-only 候选 pair 的原始顺序；它根据 `relation.failed_pair_nodes` 在 SWSD `pair_nodes` 中的位置，保留已知端点所在 SWSD 侧，只把候选中另一个 RCSD 端点填入缺失侧。
4. 补全后的 effective relation 仍必须通过原 Step2 的 single/dual direction、buffer corridor、pruning、leaf endpoint、geometry coverage、特殊路口组等全部硬审计。
5. 如果候选 pair 不包含 T05 已知端点，则不得自动补全，继续 rejected / 人工复核。
6. 对缺一个 pair 端点的场景，若 buffer-only probe 因候选组件包含旁枝导致综合分低于 `0.85`，但 status 为 `corridor_found`、connectivity / directionality 均为 `1.0`、shape similarity 不低于 `0.95`，且侧保持补全后的 effective relation 通过 Step2 全部硬审计，可记录为 `side_preserving_missing_pair_anchor_completion` 并自动进入 replaceable。该例外不适用于替换已有 T05 端点。

该规则不启用新的输入字段语义，不回写 T05 relation，也不放宽已有端点替换的 endpoint cluster 安全门。

## 质量与审计

- CRS 与坐标变换：不新增 CRS 处理，继续复用 T06 Step2 的 EPSG:3857 输入与输出约定。
- 拓扑一致性：不 silent fix；补全后仍重新执行 Step2 原有硬审计。
- 几何语义：buffer-only pair 只提供候选端点集合，不提供单向业务方向；单向方向仍只来自 SWSDRoad directed graph。
- 审计可追溯性：replaceable / failure business audit 保留 T05 原始 pair 与 T06 effective pair，repair candidates 保留 buffer-only 候选证据。
- 性能可验证性：仍为每个失败 Segment 最多一次额外 buffer extraction，summary 替换率与自动提升数量可复算。

## 验证

- 新增单元测试覆盖：单向 Segment 中 T05 缺第二个 pair relation，buffer-only 候选 pair 顺序与 SWSD 业务方向相反，且候选组件存在可剪枝旁枝导致 probe 低分时，T06 必须保留已知端点侧并补缺失侧，最终通过有向 corridor 审计并以 `side_preserving_missing_pair_anchor_completion` 进入自动补全审计。
- 真实 T10 实验确认：`1888188_1915092` 侧保持补全后通过原有硬审计；`51810921_1915092` 的候选不包含 T05 已知端点，因此仍不满足自动补全安全门。
