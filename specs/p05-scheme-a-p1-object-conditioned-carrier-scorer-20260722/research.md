# P05-Scheme-A-P1 研究决策

## 1. 为什么不继续旧 JSG-P3

旧 P3 已证明 object-conditioned interaction 有效，但它预测旧 Junction/Relation/SegmentConnector/PTO-A 选择；其中 `SegmentConnector` 和骨架重选与方案 A 冲突。当前必须重建 carrier-only candidate、label 和门禁，不能只改旧类型名称。

## 2. 为什么使用 candidate scorer

本地 51 Case 足以支持对象级 carrier 分类，但不足以支持完全自由 RoadGraph 生成。当前规则/策略能高召回产生有限候选，模型负责软判断和排序，确定性约束只保护图合法性，符合已确认业务路线。

## 3. 为什么先做 candidate reachability

如果 truth-free 候选不包含正确 Road/Node carrier，训练指标只能反映表示上限，继续增加模型容量没有意义。因此 `100% exact reachability` 是训练前 hard gate，且禁止用 label payload 补候选。

## 4. 模型量级

51 Case 包含 8,863 Segment、24,779 Movement；按确认后的 fallback 边界，可用 label 为 30,151（Segment 8,823、Movement 21,328）。首版 `1M~5M` 已足以表达 candidate/object/context 交互；更大模型提高过拟合和 Case 记忆风险，不匹配数据规模。

## 5. MIXED_CARRIER

当前只有 14 个 MIXED 正样本，不足以形成稳定独立门禁。它仍进入训练、混淆矩阵和逐 Case审计，但不单独决定 GO；后续需主动学习或新增人工样本再建立正式 recall 门。

## 6. 策略 baseline 的解释

策略 replay 可以作为 truth-free 候选来源，但策略终态/status/reason 不能成为特征。正式报告同时给出当前策略直接/正确 fallback/失败基线；模型是否 GO 由未见 Case OOF、precision-first accepted coverage 和安全 fallback 决定。
