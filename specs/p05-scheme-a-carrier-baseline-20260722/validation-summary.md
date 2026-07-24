# P05 方案 A Carrier 基线验收摘要

## 1. 结论

本阶段正式完成，结论为 **PASS**。

完成范围仅包括方案 A 的冻结业务骨架、策略基线、carrier 软标签、`RealityChangeClue` 和确定性 fallback；没有训练新模型、没有修改 T01–T12 正式实现、没有新增正式入口，也没有提交或推送 Git。

正式不可变 Run：

- Run A：`outputs/_work/p05_neural_road_generation/p05_scheme_a_baseline_20260722_12`
- Run B：`outputs/_work/p05_neural_road_generation/p05_scheme_a_baseline_20260722_13`

这两轮按用户确认的“Segment 冲突只回退该 Segment，不自动回退 Movement”口径取代 `_10/_11`；旧 run 不删除，只保留为修正前历史证据。

两轮均为 `gate_pass=true`、`skeleton_mutation_count=0`、`content_repair=false`、`silent_fix=false`，并逐文件通过 artifact SHA-256/size 复核。

## 2. 输入与范围

- 冻结 JSG-P0 输入：`p05_jsg_p0_20260721_05`。
- M0 fold/weight 输入：`p05_m0_20260721_06`。
- 数据仅来自 `E:\TestData\POC_Data`。
- Case：51；其中 T10=6、T10-Error=25、T10-Error-2=20。
- 用户排除项 `T10-Error / 1213556_1263661` 出现次数为 0。
- 全部 Case CRS 为 `EPSG:3857`。

## 3. 冻结骨架

- T01 Segment：8,863；策略 relation：8,863，逐 Segment 一一对应。
- 普通 Segment：8,389。
- `ADVANCE_RIGHT Segment`：474；当前业务输出中的旧 Connector 对象数为 0。
- PhysicalMovement：24,779；模型不存在增删目标。
- 所有 Segment/Road/Node/relation/final Road/final Node 几何均非空，六类矢量输入 CRS 一致。

ADVANCE_RIGHT 进一步核验：

- 434/474 可由独立 Road 的唯一有向端点及端点处唯一普通 Segment owner 追溯 `source_segment_access/target_segment_access`。
- 40/474 存在 owner 缺失或多解，保持 `access_valid=false`，没有按几何邻近猜测。
- 472/474 具有合法独立 SWSD Road；2 个 Road 存在端点 Node 引用缺失，不能作为合法 fallback 发布：
  - `T10:74155468 / advance_right_123cb24480306815`
  - `T10:609214532 / advance_right_a675eda6ba1c4aba`
- 上述 2 个对象包含在 40 个 access 不可确认对象内，因此当前唯一不可发布 Segment 为 40 个，而不是 42 个。

## 4. 策略基线与安全标签

原始 T06 策略结果保持原样，不被 fallback 统计覆盖：

- `SUCCESS_DIRECT`：3,083。
- `SUCCESS_WITH_FALLBACK`：5,461。
- `FAIL`：319。

方案 A carrier 标签在 hard gate 与 fallback 后为：

- Segment 标签 8,863：`USE_RCSD=2,190`、`KEEP_SWSD=6,619`、`MIXED_CARRIER=14`、`REVIEW_FALLBACK=40`。
- Segment 可用标签 8,823，mask 40。
- Movement 标签 24,779：`USE_RCSD=21,328`、`REVIEW_FALLBACK=3,451`；Segment fallback 不再遮蔽 Movement，仅 Movement 自身/Junction fallback 可 mask。
- 全部标签：33,642；可用 30,151，mask 3,491。
- 权重：`TARGET/0.7=25,641`、`CONTEXT/0.3=8,001`。
- label lineage、fold、weight、mask、`label_only=true`、`feature_uses_truth=false` 完整率均为 100%。

## 5. RealityChangeClue 与 fallback

`RealityChangeClue` 共 913 条：

- `JUNCTION_MAINNODE_CONFLICT`：543。
- `SEGMENT_ACCESS_NODE_MISSING`：227。
- `RCSD_CARRIER_ROAD_MISSING`：101；只覆盖策略宣称成功但最终 RCSD carrier 缺失，不把 319 个策略失败伪装成现实变化。
- `ADVANCE_RIGHT_ACCESS_UNRESOLVED`：40。
- `SWSD_INDEPENDENT_ROAD_INVALID`：2。

每条 clue 均有 evidence/hash lineage，并且恰好关联一个 fallback plan；clue 不是现实变化已经确认，只是需要 P04、规则补强或人工复核的输入。

fallback plan 共 1,222 条：Segment 单元 679，Junction 单元 543；`SUCCESS_WITH_FALLBACK=1,166`，`FAIL=56`。679 条 Segment plan 的 `movement_ids` 全部为空；3,451 条 Movement 引用只来自 Junction plan。56 是计划记录数，其中部分来自同一 Segment 的不同触发；实际不可发布对象仍为上述 40 个 ADVANCE_RIGHT。失败原因全部是 access 无法确认，其中 2 个同时缺少合法独立 Road。没有业务不正确却被计为成功的 fallback。

## 6. 确定性、GIS 与资源

Run A/B 五类业务签名完全一致：

- skeleton：`6b6261ae5792322f60fda5a397c3aa5d810264ece5fac2793d974d750454e051`
- strategy baseline：`2aa7a818dcd3dd7c0a263f5054f54e7f92e69d4b7169336889c5ef55053a1bcc`
- carrier labels：`0d382b17c4316a51745b156f0b7102417160c9199c6ddd1706219148b857a053`
- RealityChangeClue：`889aaa3a6628af0a5bbd4f9e4b7faeaef477d9d1bd2202a5c5b416ec770ba26d`
- fallback plans：`77402fffe55b72466192132a0ff152f9e5519cb6cb37b8874d25241174f694d4`

资源：

- Run A：wall 15.471s、CPU 1.703s、P95/max 1.104s/4.063s、RSS 416,620,544 bytes。
- Run B：wall 17.010s、CPU 0.766s、P95/max 1.230s/4.595s、RSS 466,571,264 bytes。
- GPU required=false；全部低于 SpecKit 门禁。

## 7. 测试与治理

- 方案 A 专项：16 passed。
- 当前完整 P05 回归：140 passed（包含后续 Scheme-A-P1 回归）；baseline 完成时的专项结论保持不变。
- 当前 P05 源码/测试共 119 个 `.py` 文件；`>=60KiB=0`、`>=100KB=0`，最大仍为 `scheme_a_baseline.py` 58,135 bytes。
- 两轮 run manifest 均记录当前四个 `scheme_a_*` 实现文件的绝对路径、SHA-256 和体量。
- 未新增 `scripts/`、CLI、`__main__.py`、Makefile 或 T10 stage，`entrypoint-registry.md` 无需变化。

## 8. 后续边界

本 PASS 证明方案 A 的数据与安全执行合同已经建立，不代表神经 scorer 已训练或达到业务上线标准。P1 只允许在 30,151 个可用 carrier 标签及相应 mask/lineage 上建立 grouped OOF scorer；40 个不可发布 ADVANCE_RIGHT 和 913 条 clue 应优先作为规则补强或人工复核队列，不能由模型静默改写骨架。
