# P05-Scheme-A-P2-P2-P2-P2 实施计划

## 1. 数据流

```text
P2-P2-P2-P0 evaluation/decisions
  + P2-P2-P2-P1 22 blocked objects
  + P2-P1 candidate/payload/compatibility oracle
  + Dataset-P0 module artifact inventory
  + Scheme A baseline/T03/T04/T05/T06 lineage
  -> manifest/hash/denominator gate
  -> carrier safety 与 clue visibility 指标重解释
  -> 22 对象 candidate/source route
  -> 26 Node payload conflict / 57 Junction fallback 复核
  -> deterministic Run A/B
  -> 下一模型阶段判定
```

## 2. 工件

- `scheme_a_p2_p2_p2_p2_models.py`：审计配置、业务分类与决策合同。
- `scheme_a_p2_p2_p2_p2_audit.py`：输入验证、指标重解释、源路径与 Junction 审计。
- `test_scheme_a_p2_p2_p2_p2.py`：分母、互斥、源角色、指标、闭包与破坏测试。
- 正式输出：
  - `metric_reinterpretation.json`
  - `object_source_routes.jsonl`
  - `junction_dependency_audit.jsonl`
  - `source_candidate_ledger.jsonl`
  - summary/manifest/validation report

不新增 CLI、root script、模块 `__main__` 或正式入口。

## 3. 实施顺序

1. 冻结 SpecKit、输入根、hash、22 对象和新指标合同。
2. 重算既有 `LINEAR`/`SHALLOW_MLP` 决策，不训练、不调阈值。
3. 流式读取候选并核验 5 个 no-USE、1 个 MIXED 可达性。
4. 重建 Node carrier 冲突与 Junction fallback 闭包。
5. 连接 Dataset-P0 与 T03/T04/T05/T06 只读监督 lineage。
6. 执行单测、正式 Run A/B、P05 回归、体量/入口/格式/资源检查。
7. 写 validation summary，只同步稳定结论。

## 4. 非目标

- 不以 T06 Step1/2/3 作为 P05 推理规则。
- 不训练 scorer、异常头或表征模型。
- 不修改候选、fallback、RoadGraph 或 T01–T12。
- 不因指标重解释而降低 clue 可见性要求。
