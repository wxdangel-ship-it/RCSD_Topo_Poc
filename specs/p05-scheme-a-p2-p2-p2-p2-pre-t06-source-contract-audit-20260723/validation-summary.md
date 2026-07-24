# P05-Scheme-A-P2-P2-P2-P2 验证总结

## 1. 最终结论

本阶段已完成，正式判定：

`P05_SCHEME_A_P2_P2_P2_P2_PARTIAL_ROUTE_NO_MODEL_GO`

该结论表示：现有数据和候选足以支持下一代分层模型路线，但现有浅层 MLP 仍不满足跨 Case 自动发布门禁。本阶段没有训练模型、调整阈值、修改候选、改变冻结骨架、提升 label-only 源角色或修改 T01–T12。

## 2. 业务指标重解释

旧 `unsafe` 同时包含错误 Road/Carrier 与正确 Road 但异常线索漏报。本阶段将二者拆开：

| 指标 | 浅层 MLP 全局结果 |
|---|---:|
| carrier wrong accepted | 0 |
| Review auto publish | 0 |
| carrier safety recall | 1.0 |
| clue miss only | 13 |
| clue recall | 0.994189 |
| 总体 coverage | 0.548686 |
| `USE_RCSD` coverage | 0.755729 |

13 个旧 residual unsafe 全部为正确 `KEEP_SWSD → KEEP_SWSD` 后漏报 clue，不是错误 Road 发布。

但逐 fold 只有 fold 1/3 通过完整门禁：

- fold 0 总体 coverage=`0.465054`
- fold 2 总体/USE coverage=`0.289101/0.319465`
- fold 4 总体/USE coverage=`0.037594/0.333333`

所以不能用全局零错误掩盖未知 Case 上的低自动化率。

## 3. 22 对象源路径

- 22/22 正确 candidate target 可达；
- 16 个对象为 `HIERARCHICAL_JUNCTION_CONSISTENCY`；
- 5 个对象候选只有 `KEEP_SWSD/REVIEW_FALLBACK`，Road 侧可安全 KEEP，clue 由独立异常头学习；
- 1 个对象已存在 `MIXED_CARRIER` candidate，是评分选择错误；
- 9 个真正 carrier 错误与 13 个 clue-only 漏报互斥、无遗漏。

T03/T04 节点证据、T05 relation、T06 carrier/clue 继续只作为辅助监督或评价；推理期没有读取这些终态字段。

## 4. Junction 一致性

- 初始 Node payload conflict：26
- 涉及 Case：9
- Junction fallback Segment：57
- 冻结 target：`KEEP_SWSD=36 / MIXED_CARRIER=13 / USE_RCSD=8`
- 与 P2-P1 compatibility oracle 精确一致
- 骨架 mutation、repair、silent fix：0

通用 Junction 闭包只保证共享 carrier 的图合法性，不决定业务 carrier 真值。

## 5. 正式运行与资源

- Run A：`p05_scheme_a_p2_p2_p2_p2_audit_20260723_01`
- Run B：`p05_scheme_a_p2_p2_p2_p2_audit_20260723_02`
- signature：`f50389a9d87522dd14bda8def879a815425a2cfb96f6f4cb99ff304cbba264d3`
- Run B `reference_run_match=true`
- wall：`88.478s / 85.741s`
- peak RSS：`1666.41MB / 1667.65MB`
- GPU VRAM：`0`
- RoadGraph：`49 LEGAL + 2 EXPECTED_FAIL`，冲突/错配/新增失败均为0

## 6. 测试与治理

- 本阶段专项测试：`7 passed`
- P2-P2-P2-P0/P1/P2 联合回归：`19 passed`
- P05 全量回归：`186 passed, 1 failed`
- 唯一失败仍为 WSL 下既有 `test_scheme_a_dataset_p0.py::test_resource_audit_reports_nonzero_process_memory`；正式 Run A/B 的资源采集均为非零，本阶段未修改该函数。
- `compileall` 与 `git diff --check` 通过。
- P05 `src/` + `tests/` 共 152 个源码/测试文件，`>=60KiB=0`、`>=100KB=0`，最大仍为 `scheme_a_baseline.py`（58,135 bytes）。
- 未新增/修改 repo CLI、`scripts/`、`tools/`、Makefile、T10 stage 或模块正式接口。

## 7. 下一步

下一阶段若获得授权，应训练一个分层模型，而不是继续调整当前浅层 MLP：

1. Segment carrier scorer：选择 `KEEP_SWSD / USE_RCSD / MIXED_CARRIER`；
2. T03/T04 Node evidence 与 T05 relation 作为辅助监督目标，不作推理规则；
3. 独立 RealityChangeClue head；
4. 通用 Node compatibility + Junction consistency decoder；
5. 沿用 Case-grouped 5-fold、carrier/clue 双指标和 49+2 RoadGraph 门禁。

当前阶段不构成训练授权。
