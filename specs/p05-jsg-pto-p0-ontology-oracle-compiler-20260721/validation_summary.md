# P05-JSG-PTO-P0 正式验收总结

## 结论

`P05-JSG-PTO-P0` 判定为 **GO**。51 个冻结 Case 的 JSG 本体、label-only canonical Oracle、evaluator 和 `JSG -> carrier realization -> R2 edit IR -> Road/Node` compiler 合同均达到冻结门槛。

本结论只证明“当前真值可以被 JSG 完整表达并确定性编译回合法 RoadGraph”。它不证明未来无 truth 候选可达、PTO-A/PTO-B 选择有效、神经网络跨 Case 泛化成功，也不授权生产接入。

## 正式证据

- Run A：`outputs/_work/p05_neural_road_generation/p05_jsg_p0_20260721_04`
- Run B：`outputs/_work/p05_neural_road_generation/p05_jsg_p0_20260721_05`
- 两轮均为 51/51 JSG canonical 往返精确、51/51 compiler 精确、hard failure=0、排除 Case 出现次数=0。
- 两轮 semantic、compiled RoadGraph 和 provenance signature 分别完全一致；逐 Case 选择字段差异为 0。详细值见 `determinism_audit.json`。
- 两轮各验证 carrier 引用 261,534 次，缺失引用 0；compiler 没有补路、吸附、重连或内容修复。

## 对象覆盖

| 对象 | observed | expressed | review | unexpressed |
|---|---:|---:|---:|---:|
| Junction | 9,042 | 9,042 | 418 | 0 |
| StandardSegment | 8,389 | 8,389 | 121 | 0 |
| JunctionSegmentRelation | 19,682 | 19,682 | 486 | 0 |
| PhysicalMovement | 24,779 | 24,779 | 0 | 0 |
| SegmentConnector | 69 | 69 | 26 | 0 |
| Terminal | 1,418 | 1,418 | 411 | 0 |
| loop | 0 | 0 | 0 | 0 |

`loop` 在真实 51 Case 中为零实例，只通过 schema、往返和合成边界测试，不作为真实正例通过。7 个多 THROUGH 冲突 Junction 全部保持 `REVIEW`，自动选择数量为 0。

T01 的 474 个 `advance_right` 证据被显式分层为：69 个 SegmentConnector、121 个 T06 mixed auxiliary internal carrier、284 个未物化的负向结果。69 个 Connector 中 43 个可发布，26 个因 access 无法唯一证明保持 `REVIEW`。另外 121 个 StandardSegment 缺少冻结 T06 final carrier，同样保持 `REVIEW`，没有自动补造。

## Review 与 anomaly

- `review_inventory.csv` 的 512 条 evaluator review event 由 486 条 relation 与 26 条 connector 事件组成；它不是所有对象 `review_count` 的简单相加，因为 Terminal 是 Junction 的子集，且对象状态与事件清单口径不同。
- 每轮 anomaly 共 552 条：`auxiliary_internal_carrier/INFO` 121、`carrier_unavailable/REVIEW` 121、`connector_access_unresolved/REVIEW` 26、`connector_not_materialized/REVIEW` 284。
- Review/Unknown 均保留原始 evidence 和 lineage，没有从局部样本反推新的 T01-T06 强规则。

## 性能与环境门禁

| 指标 | Run A | Run B | 门槛 |
|---|---:|---:|---:|
| 单 Case P95 wall | 6.278s | 6.320s | <=30s |
| 单 Case max wall | 18.314s | 21.840s | <=120s |
| 全量 CPU | 54.359s | 53.922s | <=1h |
| Peak RSS | 1,131,950,080 B | 1,131,982,848 B | <=16GB |
| GPU | 不需要 | 不需要 | 不需要 |

两轮均为 `label_only=true`、`content_repair=false`、`silent_fix=false`。逐 Case GPKG、JSG truth、compiler manifest、M0 RoadGraph evaluation 和 artifact hash 均保存在各自不可变 run root。

## 测试与治理

- JSG-P0 定向测试：10/10 通过。
- P05 全模块回归：72/72 通过。
- P05 `src/` 与 `tests/` 共 64 个源码/测试文件，`>=60KiB` 和 `>=100KB` 均为 0；JSG-P0 最大文件 `jsg_truth.py` 为 43,326 bytes。
- 未新增或修改 repo CLI、`scripts/`、`__main__.py`、Makefile 或 T10 stage；`entrypoint-registry.md` 无需改变。

## 下一授权边界

P0 已经完成，不需要用户补 Case 才能关闭。本次可以进入下一轮设计讨论，但 `JSG-P1` 尚未被本结果自动授权。若继续，建议下一阶段单独冻结“无 truth 高召回 JSG 候选生成 + PTO-A/PTO-B Oracle reachability”，仍先不训练 scorer；其范围和门槛需要新的任务书与用户确认。
