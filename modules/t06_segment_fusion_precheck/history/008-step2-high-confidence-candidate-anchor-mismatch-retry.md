# 008 Step2 高置信 candidate anchor mismatch 重试

- 时间：2026-06-12
- 背景：T10 剩余 rejected 漏斗显示，多条 Segment 的 T05 relation 已有两端 RCSD anchor，但 T06 buffer-only probe 在 SWSD Segment 50m buffer 内找到非 ambiguous、非人工复核的高置信 RCSD corridor；原始 T05 anchor 更接近语义点，但不能构成当前 Segment 的 RCSD 通道，符合 SWSD/RCSD 语义路口非 1V1、单向分歧/合流导致 segment 级入口侧不同的业务风险。
- 根因：T05 `intersection_match_all.geojson` 是语义路口级 `target_id -> base_id` 主关系，无法表达同一 SWSD 语义点在不同 Segment 上对应不同 RCSD 通道入口侧；T06 既有自动重试只允许缺失 pair 补全或 endpoint cluster 短桥场景，导致 `candidate_anchor_mismatch` 只能进入 repair candidate，无法在正式 extractor 已可验证的场景中自动替换。
- 变更：`pair_anchor_auto_retry.py` 放开一类受限准入：当 buffer-only probe 输出 `high_confidence_pair_anchor_candidate`、非人工复核，且 pair anchor 诊断来源为 `buffer_only_candidate_pair / candidate_anchor_mismatch`、候选分数不低于 `0.85`、候选两端完整时，允许 T06 当前 Segment 内构造候选 effective relation。
- 安全边界：该变更不回写 T05 relation，不绕过 Step2 正式 extractor；候选 relation 仍必须通过 buffer、direction、connectivity、geometry coverage、leaf endpoint、unexpected mapped semantic node 与特殊路口组门控，失败时保持 rejected / repair candidate。
- 审计：通过重试的 Segment 继续在 `t06_rcsd_repair_candidates.*` 与 `t06_rcsd_segment_failure_business_audit.*` 记录原始 RCSD pair、候选 RCSD pair、错误 SWSD 端点、candidate anchor mismatch 诊断来源与自动提升结果。
- 回归：新增 `test_step2_retries_high_confidence_candidate_anchor_mismatch`，覆盖 T05 两端已有但均落错，buffer-only 候选通过正式 extractor 后进入 replaceable 的场景。
