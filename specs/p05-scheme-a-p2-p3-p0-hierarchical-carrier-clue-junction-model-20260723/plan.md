# P05-Scheme-A-P2-P3-P0 实施计划

## 1. 数据流

```text
P2-P1 candidate/token/numeric groups
  + P2-P2-P2-P0 202-dim truth-free structural evidence
  + Dataset-P0 T03/T04/T05 label-only artifacts
  -> Case/fold/hash/source-role gate
  -> train-only auxiliary labels
  -> hierarchical candidate scorer + clue head + auxiliary heads
  -> inner-validation safety/clue threshold
  -> held-out carrier decisions
  -> generic Node compatibility + Junction consistency decoder
  -> RoadGraph materialization
  -> carrier/clue/RoadGraph gates
  -> deterministic Run A/B
```

## 2. 工件

- `scheme_a_p2_p3_p0_models.py`：配置、数据和决策合同。
- `scheme_a_p2_p3_p0_dataset.py`：冻结输入、202 维证据与 T03/T04/T05 辅助监督。
- `scheme_a_p2_p3_p0_network.py`：分层 carrier/clue/auxiliary 网络。
- `scheme_a_p2_p3_p0_training.py`：fold-local 词表、训练、阈值与 held-out score。
- `scheme_a_p2_p3_p0_oof.py`：3×5 OOF、decoder、RoadGraph、审计与不可变输出。
- `test_scheme_a_p2_p3_p0.py`：合同、泄漏、模型、阈值、fallback 与确定性测试。

不新增 CLI、root script、模块 `__main__` 或正式入口。

## 3. 实施顺序

1. 冻结 SpecKit、输入根、hash、source-role 和验收门禁。
2. 构建 8,863 Segment 的 truth-free 推理输入与 train-only auxiliary label。
3. 实现 1M–3M 分层网络和多任务损失。
4. 执行 3 seeds × 5-fold OOF，inner validation 冻结阈值。
5. 执行通用 compatibility/Junction decoder 与 RoadGraph materialization。
6. 计算逐 seed/逐 fold/整体 carrier/clue/coverage/RoadGraph 指标。
7. 完成正式 Run A/B、专项/P05 回归、体量/入口/格式/资源检查。
8. 根据 Gate 写 validation summary；仅同步稳定阶段事实。

## 4. 非目标

- 不训练或恢复 Movement。
- 不用 T03/T04/T05/T06 作为推理输入或确定性业务规则。
- 不修改 candidate、T01 Segment/Junction 骨架或 T01–T12 正式实现。
- 不以人工检查当前 held-out 输出后再调阈值。
