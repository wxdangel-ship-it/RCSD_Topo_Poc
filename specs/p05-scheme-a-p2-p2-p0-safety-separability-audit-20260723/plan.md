# P05-Scheme-A-P2-P2-P0 实施计划

## 1. 数据流

```text
P2-P1 frozen dataset manifest
  + OOF Run A/B score/selection/effective-selection
  -> hash/determinism gate
  -> truth-free Segment safety signals
  + label-only Segment/Node truth
  + compatibility edges
  -> accepted-wrong root/propagation audit
  -> Review audit + feature collision audit
  -> zero-error score-only coverage envelope
  -> P2-P2-P0 decision
```

## 2. 代码与工件

- `scheme_a_p2_p2_p0_audit.py`：内部只读审计 callable；不导出为正式模块入口。
- `test_scheme_a_p2_p2_p0_audit.py`：小型合成证据与破坏测试。
- 正式 run 输出：`safety_signals.jsonl`、`error_chains.jsonl`、`review_audit.jsonl`、`feature_collision_audit.json`、`summary.json`、`manifest.json`。

源码/测试写入前检查当前字节数；单文件保持低于 60 KiB，硬上限 100 KB。

## 3. 实施顺序

1. 冻结 SpecKit、输入 manifest 和决策口径。
2. 实现 artifact/hash、分母与 A/B 确定性验证。
3. 构建 truth-free safety signals 和独立 label-only join。
4. 追踪 Segment 根错误到 Node/Junction/effective carrier。
5. 计算 Review、feature collision 和 score-only 零错误覆盖率。
6. 运行测试、正式 A/B 审计和重复审计。
7. 完成体量、入口、证据与 source-of-truth 收口。

## 4. 非目标

- 不训练 safety head。
- 不调 P2-P1 阈值或重跑 OOF。
- 不修复 RoadGraph，不改变 fallback。
- 不修改 T01-T12 或官方执行入口。
