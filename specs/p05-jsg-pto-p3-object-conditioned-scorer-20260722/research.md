# P05-JSG-PTO-P3 研究决策

## R-001：P3 只替换 scorer

P2 已证明正确候选、PTO 与 compiler 成立。P3 修改候选或约束会破坏归因，因此仅允许改变 candidate cost/confidence。

## R-002：使用集合上下文交互网络

当前候选为离散有限集合，P1 已提供 dependency graph。首版采用 token embedding、candidate/context 双编码和乘性交互 MLP，参数小、CPU/GPU 通用，并能表达线性 V1 无法表达的“candidate state × neighbor structure”条件关系。首版不采用 40M slot-query decoder，也不引入自由图生成。

## R-003：context 必须 inference-available

同组候选、dependency/reverse-dependency、对象类型和 Case 规模均来自 P1 candidate manifest。truth 只生成训练 label 和 held-out 评价，不生成 context。ID 只用于 join，context token 不保存具体 ID。

## R-004：listwise 而非逐行二分类

191,331 个组均恰有一个 truth candidate。训练直接优化组内 softmax，可与 PTO 的 Top-1 选择一致，并避免大量负候选使逐行 BCE 偏向全负。

## R-005：Review 需要 recall 与 precision 双门禁

只提高 Review recall 可能退化为全部预测 Review；只提高总体 accuracy 又会强制发布疑难对象。因此正式门禁同时要求 Review/Unknown recall `>=0.90`、precision `>=0.80`。

## R-006：outer held-out 不参与调参

正式 outer 5-fold 只用于最终评价。early stopping 与 class weight 来自 outer train 内的 business-ID inner validation；正式 3 seeds 在超参数冻结后运行。

## R-007：RoadGraph 是 safety gate

P2 RoadGraph 100% 主要来自登记的高质量 strategy proposal carrier，不能证明 JSG scorer。P3 GO 以 JSG 为主；RoadGraph 只要求不得退化。

## R-008：在线 proposal 继续独立 NO-GO

P3 消费冻结候选，不解决历史 replay 5,751.192s 成本。即使 P3 通过，在线 proposal 和生产接入仍须独立授权和验收。
