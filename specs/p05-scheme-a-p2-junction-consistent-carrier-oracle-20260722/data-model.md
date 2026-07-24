# P05-Scheme-A-P2-P0 数据模型

- `P2SegmentCandidateRef`：P1 truth-free Segment Road candidate 的不可变引用。
- `P2NodeCarrierOption`：一个 Node ID 在 T01/proposal 中的候选 payload、source、mainnode key、semantic signature 和 lineage。
- `P2JointCandidateManifest`：candidate scope、输入/输出 hash、truth/Movement 使用计数和确定性 signature。
- `P2SegmentRoadChoice`：个体 truth candidate 或 SWSD fallback 的 Segment Road 选择。
- `P2JunctionNodeChoice`：JunctionUnit 内各 endpoint Node 的统一 mainnode key 与 payload option。
- `P2JunctionCarrierSet`：相关 Segment Road choice 与共享 Node choice 的联合终态。
- `P2RealityChangeClue`：无共同 carrier、payload 缺失、基础 SWSD 不合法或证据冲突。
- `P2OracleCertificate`：joint exact、USE_RCSD retention、fallback、RoadGraph、安全和资源结论。

Movement 不属于本数据模型的候选、选择或评价对象。
