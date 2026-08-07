# Quickstart（研究阶段）

本 SpecKit 不新增正式 CLI，也不接 T10/生产。

实施顺序：

1. 只读构建 Target A inventory 与 leakage preflight；
2. 生成 inference cache 和独立 label store；
3. 运行 anchor/ordinary/AdvanceRight 分阶段训练；
4. 生成 Case-group OOF；
5. 运行结构化 decoder、安全 gate、GIS/拓扑和完整策略 paired evaluation；
6. 输出 checkpoint、metrics、decision ledger 和 validation summary。

所有运行工件进入 ignored `outputs/_work/p05_neural_road_generation/target_a_*`，正式结论
写入本 spec 目录的 `validation-summary.md`。在安全门和业务门全部通过前，不允许接入
生产，也不允许把 fallback SWSD 计作模型自动决定。
