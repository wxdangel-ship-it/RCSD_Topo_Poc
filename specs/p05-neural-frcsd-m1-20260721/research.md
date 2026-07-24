# Research: P05 M1 数据与模型选型

## 1. 冻结数据结论

M0 `_06` 提供 51 个通过 integrity gate 的 T06 Road/Node truth，固定 split 为 `33/13/5`。M1 预审计确认 T06 输出主要可解释为 T01/T05 输入 Road 的保留、删除与切分，而不是无条件自由生成坐标。

因此 M1 选择“神经网络预测最终 Road 操作 + 确定性几何物化”，而不是只预测 T06 中间 replaceable，也不是直接训练高自由度坐标生成器。该表示仍直接产出最终 Road/Node，并把无法表达的 truth 保留在完整评价分母中。

## 2. 候选与操作预审计

只读预审计得到：

- 候选决策量约 3.75 万；
- `KEEP` 约 2.15 万，`DROP` 约 1.51 万，SPLIT 父 Road 871；
- SPLIT 子数：1 子 28、2 子 841、3 子 2；
- 子 Road 共 1716；完整 truth 中只有 14 条无法回指输入父 Road；
- operation coverage micro 值超过 99.9%，最差单 Case 约 98.6%。

正式数字必须由 M1 dataset builder 从冻结 run 重算。

## 3. 泄漏风险

M0 的业务 ID group 能阻止相同 Case/Segment 版本跨 fold，但 M1 候选级预审计仍发现少量相同 Road ID 位于不同 split。原因是不同局部 Case 的空间裁剪可能重叠，或标准 Case 包含局部错误 Case 的道路。

M1 采用实体优先级 `test > validation > train`。重复 Road及其一跳邻域只保留在最高优先级 split，低优先级图中完全移除，而不是仅把 loss 权重设零。ID 只用于 lineage/泄漏审计，不进入模型数值特征。

## 4. 模型选择

### 选择

采用原生 PyTorch 稀疏 gated GraphSAGE/Graph Transformer block，默认 hidden `384`、6 层、FFN expansion `4`。预计参数量约 10M。

### 原因

- 3.75 万候选决策足够训练小型图模型，但不足以支撑高自由度大模型；
- 单 Case 最大约 1 万候选 Road，稠密 attention 的二次复杂度不可接受；
- 稀疏共享端点/邻域图更符合 RoadGraph 结构；
- 原生 PyTorch 避免 `torch_geometric`/CUDA 扩展的安装与复现风险。

### 不选择

- 大型 Transformer：样本量与显存收益不匹配；
- 仅 MLP：作为基线，不能建模拓扑关系；
- 只预测 Segment replaceable：不是最终 Road 直出；
- diffusion/polyline autoregressive：M1 数据规模不足，留到 M2 评估。

## 5. 评价策略

固定 test 只有 5 个 Segment Case且标准 T10 为 0，统计强度不足。开发阶段只用 train/validation 和开发集 group CV；架构冻结后执行标准 T10 shadow holdout，再一次性评估固定 test。最终结论必须声明这些分布限制。

