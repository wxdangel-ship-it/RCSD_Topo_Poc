# Research: P05-R2 表示与模型路线

## 决策 1：从候选分类升级为显式 graph edit-set

R1/M2R 的 `DROP/KEEP/SPLIT_1..3` 只覆盖 `86.79%` truth，无法表达新增 Road、精确 Node 和任意数量 split child。R2 使用 Road `COPY/UPDATE/SPLIT/CREATE/DROP` 与 Node `COPY/UPDATE/CREATE/DROP`。`CREATE` 是完备性兜底，不是业务 fallback；其内容必须由模型生成。

## 决策 2：Gate 1 使用 oracle payload，但严格 label-only

oracle 读取 truth 形成动作、对象 payload 和精确 pointer，只用于证明表示能力与监督。所有 oracle artifact 均登记 `label_only=true`，不得进入推理特征。这样可以把“语言不完备”与“模型学不会”分离。

## 决策 3：等价性采用归一化语义图

不要求 GPKG 二进制 hash 相同；要求 Road/Node 对象、ID、属性、端点、几何和有向边在冻结 evaluator 下完全一致。内部路口 split、source 与 carrier 语义必须保留，不能只比较数量。

## 决策 4：T05 使用 pointer，而不是 endpoint membership

每个 target 在显式 base candidate 集合中选择唯一 base 或 `NO_MATCH`。训练/评价分别审计 pointer accuracy、base existence、target cardinality 和无候选情况。

## 决策 5：R2 默认关闭 T07

M2R T07 只提升 `0.54pp`，未减少 hard failure 且最差 Case下降。R2 不再消耗主实验资源，除非后续另有新证据。

## 拒绝方案

- 继续扩大 R1 候选分类模型：表示上限已低于目标。
- 用通用约束补齐业务内容：约束只能阻止非法图，不能决定缺失 Road。
- 将 truth-derived proposal 作为输入：会形成标签泄漏。
- 先补更多 Case：当前首先要解决表示能力，新增数据不能修复无法表达的目标。

