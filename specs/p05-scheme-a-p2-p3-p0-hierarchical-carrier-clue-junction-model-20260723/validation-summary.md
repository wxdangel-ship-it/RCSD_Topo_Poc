# P05-Scheme-A-P2-P3-P0 验证总结

## 1. 最终结论

本阶段已完成，正式判定：

`P05_SCHEME_A_P2_P3_P0_MODEL_NO_GO`

该结论表示：

- 分层模型、通用 Node/Junction decoder 和整图安全生成链路均已实现；
- 2.818M 参数模型没有使用 T03–T06 终态作为推理输入；
- RoadGraph、source-role、参数量、确定性、资源和性能门全部通过；
- 但 carrier 安全/覆盖率与 RealityChangeClue 稳定性没有同时通过 3 seeds × 5-fold 门禁，因此不得自动发布。

这不是“神经网络无法生成合法 RoadGraph”的结论。它说明当前共享表征、多任务辅助监督与 inner-validation 阈值方案，在冻结 51 Case 上仍不能稳定区分“可安全自动替换”和“必须 fallback/报 clue”。

## 2. 正式模型与数据

- 51 Case、8,863 Segment；
- 3 seeds × 5 held-out folds；
- 参数量：`2,818,234–2,818,810`，差异来自 fold-local 词表；
- 推理输入：P2-P1 truth-free candidate/token/numeric、P2-P2-P2-P0 冻结 202 维 T01/T07/结构证据；
- 辅助监督：7 个 T03/T04/T05 label-only target；
- T03/T04/T05/T06 推理特征、ID、绝对坐标、Movement：全部为 0；
- T07：`DRIVEZONE_ONLY`；
- 冻结骨架 mutation、geometry 修改、坐标变换、silent fix：全部为 0。

## 3. Carrier 结果

按 seed 的整体结果：

| seed | wrong accepted | Review auto | safe coverage | USE coverage |
|---:|---:|---:|---:|---:|
| 311 | 1 | 0 | 0.5917 | 0.7626 |
| 313 | 1 | 0 | 0.5917 | 0.7626 |
| 317 | 0 | 0 | 0.1327 | 0.2333 |

seed 311/313 的错误对象相同：

`T10-Error:1029603_1043020 / Segment 1049466_991125`

模型把真值 `KEEP_SWSD` 错误选择为 `USE_RCSD`。seed 317 通过大量 fallback 避免了错误，但覆盖率远低于 0.50。

fold 2 在三个 seed 上的总体 coverage 均约 `0.29`，`USE_RCSD` coverage 约 `0.32`，说明低覆盖不是单一随机 seed 现象。

## 4. RealityChangeClue 结果

| seed | clue recall | clue precision | macro F1 | 已知 13 clue-only 捕获 |
|---:|---:|---:|---:|---:|
| 311 | 0.9844 | 0.9968 | 0.9937 | 9/13 |
| 313 | 0.9852 | 0.9973 | 0.9941 | 8/13 |
| 317 | 0.9987 | 0.3502 | 0.5316 | 12/13 |

seed 311/313 是高精度但有漏报；seed 317 接近全召回，但大量误报导致自动化率崩塌。三个 seed 均未达到 high-risk recall=`1.0` 和 13/13 捕获。

## 5. Junction 与 RoadGraph

三个 seed 均精确通过：

- `49 LEGAL + 2 EXPECTED_FAIL`
- requirement conflict=`0`
- Node target mismatch=`0`
- Node payload conflict=`0`
- hard-gate repair/fallback iteration=`0`
- skeleton mutation=`0`

这证明“模型软判断 + 通用 Node compatibility/Junction consistency decoder”可以生成合法整图；NO-GO 来自业务 carrier/clue 识别，不来自 carrier 来源冲突或整图合法性。

## 6. 双跑、资源与性能

- Run A：`p05_scheme_a_p2_p3_p0_oof_20260723_01`
- Run B：`p05_scheme_a_p2_p3_p0_oof_20260723_02`
- signature：`d6974ccaa140442412cf793d1379dc3a3232a1bba9b874207dcb12d7faddff59`
- Run B `reference_run_match=true`
- wall：`403.32s / 373.59s`
- peak RSS：`2.43GB / 2.44GB`
- GPU VRAM：`0`
- 每 seed 五折训练最大：`86.07s / 92.17s`
- Case 推理 p95：`0.0539s / 0.0437s`
- Case 推理 max：`0.1644s / 0.1235s`

## 7. 测试与治理

- 本阶段专项测试：`5 passed`
- P2-P2-P2-P0/P1/P2 + P2-P3-P0 联合回归：`24 passed`
- P05 全量回归：`191 passed, 1 failed`
- 唯一失败仍为既有 WSL 环境下 `test_scheme_a_dataset_p0.py::test_resource_audit_reports_nonzero_process_memory`；P2-P3-P0 两轮正式资源采集均为非零，本阶段未修改该函数。
- P05 `src/` + `tests/` 共 158 个源码/测试文件，`>=60KiB=0`、`>=100KB=0`；最大仍为 `scheme_a_baseline.py`（58,135 bytes）。
- 未新增/修改 repo CLI、`scripts/`、`tools/`、Makefile、T10 stage 或模块正式接口。

## 8. 后续边界

不得在当前 held-out 51 Case 上继续调 threshold、挑 seed 或扩大同一模型后重报 GO。

下一阶段若另行授权，应先做失败归因与新验证设计，重点处理：

1. 同一对象在 seed 311/313 稳定错误接受的问题；
2. fold 2 稳定低覆盖；
3. clue 的“高精度漏报”与“高召回过报”两种校准极端；
4. 引入新冻结验证证据或真正新的推理期表征，而不是把 T03–T06 label-only 字段提升为输入。
