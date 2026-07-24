# P05-Scheme-A-P1 数据模型

| 对象 | 作用 | 关键约束 |
|---|---|---|
| `SchemeAP1Candidate` | 一个 Segment/Movement carrier 或 fallback 选项 | `truth_derived=false`；ID 只 join，不进 feature |
| `SchemeAP1CandidateGroup` | 同一业务对象的有限 candidate set | 至少含 safe fallback；exactly-one score selection |
| `SchemeAP1FeatureRow` | candidate/object/context token 与 numeric feature | 无 truth/ID/绝对坐标；fold-specific vocabulary |
| `SchemeAP1Label` | label-only 正确 candidate 与 anomaly target | 只在 candidate manifest 冻结后 join |
| `SchemeAP1Checkpoint` | 某 seed/outer fold 模型 | 记录 train/inner/held-out、vocabulary、normalization、hash |
| `SchemeAP1Score` | candidate cost/confidence/uncertainty | 100% candidate 覆盖；可由 checkpoint 重放 |
| `SchemeAP1FallbackDecision` | 模型或 hard gate 触发的最小闭包 fallback | 不改变 frozen skeleton |
| `SchemeAP1RoadGraph` | 选中 carrier 的 Road/Node 逻辑物化 | CRS/ID/引用/方向/拓扑合法；no repair |
| `SchemeAP1Evaluation` | OOF、稳定性、安全和资源指标 | 51 Case、3 seeds，不隐藏失败对象 |

## Candidate 字段分层

- join/audit：`case_key/object_id/candidate_id/group_id/payload IDs/path/hash`。
- model feature：ID-free categorical token、局部归一化 numeric、context aggregate。
- label-only：`truth_candidate_id/carrier_target/target_payload/anomaly_target/weight`。

## 决策状态

- `PUBLISH_CANDIDATE`：达到 precision-first threshold 且 hard gate通过。
- `MODEL_FALLBACK`：低置信或高异常概率。
- `HARD_FALLBACK`：结构/候选/CRS/引用/现实冲突。
- `FAIL`：fallback 后仍不满足合法性。
