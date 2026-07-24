# Research: P05 M2R

## R1 - 为什么不能直接沿用 M1

M1 把 T03/T04/T05/T07 作为模型输入 artifact，只学习 T06 Road 操作。固定 test Road F1 `0.6436`，keep-all `0.6521`，5/5 Case 有向拓扑不同。用户当前目标要求模型自身包含 T03/T04/T05/T06，因此属于新的监督与架构假设，不能只继续调 M1 超参数。

## R2 - 当前数据事实

- M0 登记 741 样本、726 group、740 可用样本。
- T03/T03_Error 登记 336 个单点对象 Case。
- T04/T04_Error 登记 353 个单点对象 Case。
- T10/T10-Error/T10-Error-2 登记 52 个 RoadGraph lineage，其中 1 个批准排除，51 个可用于 RoadGraph。
- 当前 M0 只为 T10 lineage 登记 T01-T07/T06 artifact；T03/T04 单点 bundle 多数只包含输入 GPKG 和 manifest，不能假定存在 surface/relation 真值。
- `Error` 目录不能作为负类；用户已确认当前正式 T03/T04 策略在这些 Case 上的成功/失败结果均可视为人工真值，因此允许参数化重放，但必须逐 Case 记录输入和终态 lineage。

## R3 - 任务分解决策

- T03：目标节点状态/场景/关联；surface/relation 由用户确认的策略重放或其它可追溯产物启用。
- T04：目标节点状态/事件/关联；surface/relation 由用户确认的策略重放或其它可追溯产物启用。
- T05：融合 surface、唯一 relation、junctionized Road/Node。
- T06：最终 Road operation、属性、端点和有向图。
- T07：已有路口面锚定辅助任务，不作为主实验阻塞项。

这种分解允许单点 Case 训练局部任务，同时让 51 个 T10 Case 训练最终 RoadGraph；缺失任务通过 mask 跳过。

## R4 - 解码边界

选择“模型决定业务内容，通用约束保证形式合法”：

- 允许：schema、ID 唯一、引用存在、有限非空几何、生成动作状态合法。
- 禁止：Segment 归属、Road 合并/SPLIT、方向、主路、路口映射、补路、强制全图连通。
- 约束在解码时屏蔽非法动作；生成后不得修图。

free decoder 保留为研究对照。若 constrained 只解决合法性而语义指标相同，可证明通用约束有工程价值；若语义本身失败，问题仍在数据/表示/模型。

## R5 - 泛化评价决策

M1 固定 test 已被访问，不能继续作为盲测。M2R 主要结论使用 business-ID grouped out-of-fold：每个 Case 的预测来自没有训练过该 group 的模型。历史五 Case test 只作回归说明，不参与模型选择。

## R6 - 模型规模与资源

采用共享 vector/graph encoder 与轻量任务 Head，目标 `8M~20M`。当前 M1 约 10M 模型峰值 VRAM 约 4.7GB；M2R 为多任务留出 `16GB` 预算，仍限定单 RTX 5090，不引入分布式训练。

## R7 - 首个实施门禁

在实现联合模型前，必须先运行 supervision readiness audit。其目标不是强行达到某个标签覆盖率，而是让每个登记样本的每个任务都得到“可用标签或明确不可用原因”。如果关键类别无法进入至少三个独立 fold，阶段可以形成数据 no-go 结论，但不能伪造训练结果。
