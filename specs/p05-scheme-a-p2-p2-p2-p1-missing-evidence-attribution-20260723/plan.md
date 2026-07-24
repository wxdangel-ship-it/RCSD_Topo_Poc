# P05-Scheme-A-P2-P2-P2-P1 实施计划

## 1. 数据流

```text
P2-P2-P2-P0 9 error / 40 Review / MLP decisions
  + P2-P1 dataset labels / compatibility oracle / OOF selections
  + Scheme A T01 inventory / carrier labels / fallback / RealityChangeClue
  -> manifest/hash/denominator gate
  -> audited-object union
  -> direct-cause attribution
  -> auxiliary inference-signal audit
  -> INFERENCE_EVIDENCE_AVAILABLE
     | SOURCE_FACT_BLOCKED
     | UNOBSERVABLE_FALLBACK
  -> deterministic replay + next-stage decision
```

## 2. 工件

- `scheme_a_p2_p2_p2_p1_models.py`：只读审计配置与三类终态合同。
- `scheme_a_p2_p2_p2_p1_audit.py`：输入验证、逐对象归因、证据候选、确定性与输出。
- `test_scheme_a_p2_p2_p2_p1.py`：终态互斥、直接/辅助证据边界和破坏测试。
- 正式输出：`object_attribution.jsonl`、`evidence_candidate_ledger.jsonl`、`source_contract.json`、summary/manifest/report。

不新增 CLI、root script、模块 `__main__` 或正式入口。

## 3. 实施顺序

1. 冻结 SpecKit、正式输入根、hash 和三类终态。
2. 重建 9 error、残留 unsafe、40 Review 的唯一对象集合。
3. 连接 T01 直接证据、T06 label-only 直接来源和 P05 辅助信号。
4. 完成逐对象归因与证据候选成本/lineage 审计。
5. 独立 Run A/B、专项回归、P05 回归、体量/入口/格式检查。
6. 写 validation summary，只同步稳定结论。

## 4. 非目标

- 不训练 scorer 或表征模型。
- 不运行 T01–T12 策略重放。
- 不修改候选、阈值、fallback 或 RoadGraph 实现。
- 不对 `SOURCE_FACT_BLOCKED` 作业务授权推断。

