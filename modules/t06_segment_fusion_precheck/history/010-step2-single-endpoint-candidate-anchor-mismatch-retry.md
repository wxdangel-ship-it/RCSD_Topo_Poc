# 010 Step2 单端 candidate anchor mismatch 重试准入

- 时间：2026-06-12
- 背景：T10 `required_semantic_nodes_not_connected_in_buffer` 漏斗中，部分高置信 `candidate_anchor_mismatch` 并不是两端都错，而是一端 T05 pair anchor 已经正确、另一端受 SWSD/RCSD 语义路口非 1V1 或分歧合流影响锚到不适合作为当前 Segment 入口的 RCSD 语义节点。
- 根因：T05 `intersection_match_all.geojson` 是语义路口级主关系，不能表达同一 SWSD 语义路口在不同 Segment 方向上的局部 RCSD 通道入口。T06 既有 `candidate_anchor_mismatch` 自动重试安全门只允许两端候选错误端点均被定位的场景，导致单端错误只能输出 repair candidate，不能进入正式 extractor 复核。
- 变更：`pair_anchor_auto_retry.py` 将 `buffer_only_candidate_pair / candidate_anchor_mismatch` 的候选错误端点数量从必须等于 2 放宽为 1 到 2；候选仍必须来自非 ambiguous、非人工复核的 `high_confidence_pair_anchor_candidate`，候选分数不低于 `0.85`，并且仅在 T06 当前 Segment 内构造 effective relation。
- 安全边界：该变更不回写 T05 relation，不扩大 buffer，不绕过 Step2；候选 relation 仍必须通过 buffer、single/dual direction、connectivity、geometry coverage、leaf endpoint、unexpected mapped semantic node 与特殊路口组等正式硬审计。任一硬审计失败仍保持 rejected / repair candidate。
- 审计：通过重试的 Segment 继续在 `t06_rcsd_repair_candidates.*` 与 `t06_rcsd_segment_failure_business_audit.*` 记录原始 RCSD pair、候选 RCSD pair、错误 SWSD 端点、错误原始 anchor、候选 anchor、diagnostic source / reason 与自动提升结果。
- 回归：新增 `test_step2_retries_single_endpoint_candidate_anchor_mismatch`，覆盖 T05 已有两端 anchor 但仅一端落错、候选 pair 通过正式 extractor 后进入 replaceable 的场景。
