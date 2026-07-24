# P05-JSG-PTO-P2 研究决策

## R-001：P2 不直接训练神经网络

P1 已证明正确候选存在、PTO 可解和 compiler 正确，但尚未证明复杂模型必要。P2 先以 V0/V1 判断推理证据的排序上限，避免把候选、约束或证据问题误归因于模型容量。

## R-002：V1 使用无新增依赖的加性线性基线

使用训练折内平滑 feature log-odds 形成稀疏加性 cost。它具有明确权重、可逐候选重放、不需要新增 sklearn/GBDT 依赖，并足以回答可解释评分是否能跨 Case 泛化。

## R-003：复用 M0 split，不重新随机切分

已访问过固定 test；P2 以 M0 business-ID grouped 5-fold 为唯一 OOF 口径。每个 Case 恰好一次 held-out，训练统计不含 held-out label。

## R-004：评分与 proposal 性能分离

P2 只消费冻结/缓存候选，避免历史 5,751.192s replay 混淆排序诊断。在线 proposal generator 仍是独立技术债。

## R-005：P2 完成不等于指标 GO

即使 V0/V1 未达到最终 RoadGraph 门禁，只要证据能明确证明失败位于评分且所有审计完整，P2 实验仍可完成，并为是否启动 P3 提供依据。
