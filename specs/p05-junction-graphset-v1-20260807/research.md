# 现状研究与决策依据

## 1. 已继承的实验事实

- 旧自由 RoadGraph 模型失败不能推导神经网络整体不可用，但证明自由 pointer 生成与
  当前样本规模不匹配。
- P13 只解决 AdvanceRight 局部候选评分，无法观察相邻普通 Segment 的最终状态，范围
  小于目标 A；本轮不继续该路线。
- 旧 Junction-first P0 的主要状态 accuracy 为 0.83–0.97，但完整 anchor exact 只有
  `879/1145=0.767686`，且存在危险自动接受；说明状态头可学，完整对象集合和 free-run
  条件传播仍是核心问题。
- 完整 `JunctionResult` 审计证明 REQUIRED 候选 100% 可达，当前瓶颈不是候选缺失。

## 2. 可复用资产

- 城市级原始证据 store、唯一 Junction 身份和 Case-disjoint split。
- 21D 几何 token、8D RCSD 拓扑边、对象 span 与 truth-free 候选枚举。
- 强 Gold 602、T10 弱标签 3,686 及 task mask/权重。
- 1,680 条虚拟面三态约束、完整对象/主锚定/打断/拓扑可用标签。
- 候选约束 decoder、acceptable-set loss、确定性 materializer 和安全 ledger 的可复用
  思路；旧网络 checkpoint 不作为新结构初始化的强制依赖。

## 3. 技术选型

采用角色分离 Graph/Set encoder + 分阶段多任务 heads + 候选约束 structured decoder。
它保留一个联合系统共享原始几何/拓扑表示，同时通过输入视图和 stop-gradient 守住
Step1 与锚定前置语义；相比扁平 583D MLP 更适合变长对象集合，相比自由生成更符合
现有样本和安全约束。

建议总参数量 5–8M，隐藏维 192，4 层 Graph Transformer，2 层 SWSD query 对 RCSD
对象 cross-attention。参数量不是验收指标；若更小结构满足完整结果门禁，优先采用。

## 4. 仍需以技术审计关闭的问题

- 64D/12D 兼容特征逐维来源：原始字段、派生几何、候选元数据或禁用。
- 59/107 条 T10 success 的规范化拓扑缺失版本差异，统一以最新 overlay 和 mask 为准。
- 城市级 mmap 分片、token-budget batch 和 embedding cache 的峰值内存/吞吐基线。
- `RealityChangeClue=true` 监督不足；P0 保持禁用，不阻塞其余路口结果。

上述是实现前技术检查，不再打开已确认业务边界。
