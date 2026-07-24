# P05-Scheme-A-P2-P2-P2-P1 验证总结

## 1. 最终结论

本阶段已完成，正式判定：

`P05_SCHEME_A_P2_P2_P2_P1_SOURCE_FACT_BLOCKED`

该结论表示 62 个重点对象均已找到直接原因，但其中 22 个对象的直接判定事实只存在于当前 label-only 的 T06/联合真值层，尚未被授权为推理期输入。它不表示 Case 不足、候选缺失、RoadGraph 无法闭合或神经网络整体不适用，也不授权将 T06 终态事实直接提升为模型输入。

## 2. 正式输入

- P2-P2-P2-P0：`p05_scheme_a_p2_p2_p2_p0_audit_20260723_04`
- P2-P1 dataset：`p05_scheme_a_p2_p1_dataset_20260723_01`
- P2-P1 OOF：`p05_scheme_a_p2_p1_oof_20260723_01`
- Scheme A baseline：`p05_scheme_a_baseline_20260722_12`
- Case / Segment：`51 / 8,863`
- 所有输入 manifest、正式输出 hash 与冻结分母均通过。

## 3. 逐对象归因

三类审计对象的唯一并集为 62：

| 对象集合 | 数量 | 直接原因 | 终态 |
|---|---:|---|---|
| 40 Review | 40 | `T01_ADVANCE_RIGHT_ACCESS_INVALID` | `INFERENCE_EVIDENCE_AVAILABLE` |
| 9 个一致错误 proposal | 8 | `TRUTH_CONDITIONED_JUNCTION_FALLBACK_OVERRIDE` | `SOURCE_FACT_BLOCKED` |
| 9 个一致错误 proposal | 1 | `T06_SEGMENT_RELATION_CARRIER_TRUTH` | `SOURCE_FACT_BLOCKED` |
| 浅层 MLP 残留 unsafe accepted | 8 | `TRUTH_CONDITIONED_JUNCTION_FALLBACK_OVERRIDE` | `SOURCE_FACT_BLOCKED` |
| 浅层 MLP 残留 unsafe accepted | 5 | `T06_RCSD_CARRIER_ROAD_MISSING` | `SOURCE_FACT_BLOCKED` |

终态汇总：

- `INFERENCE_EVIDENCE_AVAILABLE=40`
- `SOURCE_FACT_BLOCKED=22`
- `UNOBSERVABLE_FALLBACK=0`
- 新增且已获准的直接推理证据：`0`

40 个 Review 已由冻结 T01 `access_valid=false` 硬门直接解释，不需要交给模型重新学习。22 个阻断对象不存在“完全不可观察”的问题，但其直接来源当前只允许用于监督、归因和评价。

## 4. 辅助信号审计

P2-P1 truth-free joint fallback 信号可以在推理期生成，但不能替代直接业务事实：

| seed | fallback 数 | unsafe 数 | unsafe precision |
|---:|---:|---:|---:|
| 17 | 3,418 | 787 | 0.230252 |
| 29 | 3,255 | 678 | 0.208295 |
| 43 | 1,949 | 581 | 0.298102 |
| 任一 seed | 4,342 | 1,098 | 0.252879 |

该信号与风险有关，但误报远多于真正 unsafe，只能作为模型/Review 辅助线索，不能升级为 Junction fallback 硬事实。

## 5. 确定性与资源

正式运行：

- Run A：`p05_scheme_a_p2_p2_p2_p1_attribution_20260723_01`
- Run B：`p05_scheme_a_p2_p2_p2_p1_attribution_20260723_02`
- determinism signature：`b7abcf3c68f6d2ee6bc36ff2ba38d28d785c2e7461e8617b7eb6f5a4edcb3bce`
- Run B `reference_run_match=true`
- wall：`15.147s / 16.079s`
- peak RSS：`335.75MB / 335.53MB`
- GPU VRAM：`0`

两轮对象集合、逐对象终态、证据候选、分类计数和决策完全一致。未训练模型、未调阈值、未修改几何、未做坐标变换、未 silent fix、未改变冻结骨架。

## 6. 测试与治理

- 本阶段专项测试：`5 passed`
- P2-P2-P2-P0 + P2-P2-P2-P1 联合回归：`12 passed`
- P05 全量回归：`179 passed, 1 failed`
- 唯一失败：既有 `test_scheme_a_dataset_p0.py::test_resource_audit_reports_nonzero_process_memory` 在 WSL 下读取既有 `_peak_rss_bytes()` 为 `0`；本阶段未修改该实现，正式本阶段 Run A/B 的资源采集均为非零。
- `compileall`：通过
- `git diff --check`：通过
- P05 `src/` + `tests/` 源码/脚本共 `149` 个，`>=60KiB=0`、`>=100KB=0`；最大仍为 `scheme_a_baseline.py`（`58,135` bytes）。
- 未新增或修改 repo CLI、`scripts/`、`tools/`、Makefile、T10 stage 或模块正式接口。

## 7. 下一步边界

本阶段不支持继续在同一 202 维证据上扩模型、加 epoch 或调阈值。下一阶段只能在业务确认后选择：

1. 保持 T06/联合真值为 label-only，把 22 个对象固定为强制 fallback/Review，继续做不自动发布的离线排序。
2. 找到能在 T06 之前独立生成、且业务语义等价的原始/策略证据，另立 source-contract 审计；通过后才允许作为新增推理证据。
3. 若推理期直接运行 T06 再读取其终态事实，则 P05 只能作为 T06 后处理器，不能再宣称替代 T06。

任何选择均不自动授权训练、T01–T12 改动、生产接入或 Git 提交/推送。
