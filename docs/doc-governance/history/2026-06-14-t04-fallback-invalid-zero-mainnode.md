# 2026-06-14 T04 fallback 禁止 mainnodeid=0 伪造成语义路口

## 背景

Case `991176` 中，SWSD Segment `991159_1049534` 的内部 SWSD 语义路口 `987955` 在 T04 Step7 面结果中被判定为 `multi_component_result`，但 relation fallback 又依据 `required_rcsd_node_ids=5396513947461929` 输出了 `status_suggested=0`。

原始 RCSDNode `5396513947461929` 的 `mainnodeid=0`，该值不能证明它是 RCSD 语义路口 group。T04 fallback 将 `0` 当作可用 group id，会形成不可被 T05/T06 正确消费的伪成功关系。

## 变更

- 在 `relation_fallback.py` 的 fallback 判定中增加 RCSD group id 有效性检查。
- 当 required RCSD node 映射到 `0` / `-1` / 空 group id 时，fallback 保持失败，审计原因输出为 `invalid_rcsdnode_group_id:<node>=<group>`。
- 在 T04 契约中明确：`RCSDNode.mainnodeid=0` 只能说明未归属多节点组，不能被 Step8 fallback 单独解释为 RCSD 语义路口。
- 增加单测覆盖 `required_rcsd_node_ids` 对应 `mainnodeid=0` 的场景，确保 `status_suggested` 仍为 `1`。

## 预期影响

- T04 不再向下游发布 `base_id_candidate=0` 或由 `mainnodeid=0` 推导出的伪语义路口关系。
- 对 `991159_1049534`，该修复用于纠正上游审计事实，不会直接把该 Segment 变为可替换；后续仍需基于 T05/T06 的真实 RCSD 双向连通结果判断是否应替换。
- 若后续需要把单节点 RCSDNode 判定为语义路口，必须由正式语义路口构建逻辑证明，不得由 fallback 根据单个字段反推。

## 验证

- `pytest tests/modules/t04_divmerge_virtual_polygon/test_relation_fallback.py -q`
- 复跑 Case `991176`，核对 `987955` 的 T04 relation fallback 审计不再输出成功关系，并继续追踪 `991159_1049534` 的 RCSD Segment 构建失败根因。
