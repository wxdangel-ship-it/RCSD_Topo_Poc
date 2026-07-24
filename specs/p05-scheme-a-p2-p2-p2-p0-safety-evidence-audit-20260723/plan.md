# P05-Scheme-A-P2-P2-P2-P0 实施计划

## 1. 数据流

```text
frozen P2-P1 candidates/base OOF
  + P2-P2-P0 error ledger
  + P2-P2-P1 formal decisions
  + allowed T01/T07/proposal/compatibility evidence
  -> source-role whitelist + hash/leakage gate
  -> label-free enriched Segment evidence manifest
  + label-only unsafe/correctness join
  -> linear probe + shallow MLP nested Case cross-fit
  -> accept / Segment fallback
  -> conditioned Node closure + RoadGraph hard gate
  -> deterministic replay + evidence GO / NO-GO
```

## 2. 工件

- `scheme_a_p2_p2_p2_p0_models.py`：schema/config/evidence role contract。
- `scheme_a_p2_p2_p2_p0_evidence.py`：truth-free evidence 构建和逐对象账本。
- `scheme_a_p2_p2_p2_p0_probe.py`：线性/浅层 MLP probe 与嵌套 Case cross-fit。
- `scheme_a_p2_p2_p2_p0_audit.py`：正式双跑、Node/RoadGraph、门禁和证据输出。
- 对应专项测试；不导出正式 CLI/模块入口。

所有源码/测试写入前检查当前字节数；目标单文件低于 60 KiB，硬上限 100 KB。

## 3. 实施顺序

1. 冻结 SpecKit、源角色白名单和正式输入 hash。
2. 盘点现有 candidate payload/compatibility/T01/T07 证据，确认没有 label-only 提升。
3. 构建 label-free evidence manifest 与独立 label-only join。
4. 实现两个预登记低容量 probe 和 nested Case cross-fit。
5. 执行 Segment fallback、Node 条件化和 51 Case RoadGraph。
6. 正式双跑、专项/历史回归、体量/入口/资源审计。
7. 写入 validation summary；只同步稳定事实结论。

## 4. 非目标

- 不修改或重训 P2-P1/P2-P2-P1 模型。
- 不使用 T03/T04/T05/T06 label/status/reason 作为 feature。
- 不新增 Road/Node candidate，不处理 Movement。
- 不在已见 held-out Case 上循环试特征或调阈值。
