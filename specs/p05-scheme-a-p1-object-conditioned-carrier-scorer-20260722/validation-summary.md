# P05-Scheme-A-P1 验收摘要

## 1. 结论

本阶段已按 `specify / plan / tasks / implement` 完成，正式结论为 **`P05_SCHEME_A_P1_MODEL_NO_GO`**。

NO-GO 的直接原因是三个 seed 的 accepted coverage 均低于 `0.50`；seed 29/43 的 anomaly precision 还低于 `0.80`。这不是 RoadGraph 安全失败，也不是模型没有学会 Segment/Movement carrier：三个 seed 的 Segment macro-F1 为 `1.0000 / 1.0000 / 0.9869`，Movement exact 均为 `1.0000`，49 个 Case 全部合法，两个登记 SWSD 缺陷 Case 全部精确输出 `EXPECTED_FAIL`。

本结论不授权生产接入，不修改 T01–T12，不提交或推送 Git。旧 M1/M2R/R2/PTO/JSG-PTO 与本轮 development run 均保留为历史实验证据。

## 2. 正式输入与不可变证据

- Scheme A baseline：`p05_scheme_a_baseline_20260722_12/_13`。它们按用户确认的“Segment 不连带 Movement”口径取代 `_10/_11`。
- truth-free candidate：`p05_scheme_a_p1_candidate_20260722_09/_10`。
- label-only dataset：`p05_scheme_a_p1_dataset_20260722_06/_07`。
- 正式 OOF：`p05_scheme_a_p1_oof_formal_20260722_01`，固定 seeds=`17/29/43`、每 seed 5 folds。
- 同 seed 重放：`p05_scheme_a_p1_oof_replay_seed17_20260722_02`。
- truth-exact 执行对照：`p05_scheme_a_p1_oracle_execution_20260722_01`。
- QGIS 审计：正式 OOF 下的 `qgis_gis_audit.json`，可复现脚本为 `outputs/_work/p05_neural_road_generation/p05_scheme_a_p1_qgis_audit_20260722_01.py`。

数据范围仍只有 `E:\TestData\POC_Data` 的 51 Case；排除项 `T10-Error / 1213556_1263661` 出现 0 次。

## 3. Fallback 业务边界修正

本轮先落实用户最终确认的方案 A：

- Segment 冲突只回退该 Segment，不自动改变或回退 PhysicalMovement；
- Movement 只因自身候选、低置信或 carrier 冲突回退；
- 仅当该 Movement 的 carrier 确实共享或影响 Junction 内部拓扑时，才升级为 Junction fallback。

双跑结果证明骨架、策略基线和 913 条 `RealityChangeClue` 均未变化。679 条 Segment fallback plan 的 `movement_ids` 全部归零；可用 Movement 标签由 16,129 恢复为 21,328，仍有 3,451 条因 Movement 自身/Junction fallback 而 mask。全部可用标签由 24,952 增至 30,151。

## 4. Gate 0：候选、范围与泄漏

- Case：51；fold：5；每个 Case 恰好一次 outer held-out。
- 对象组：33,642；候选：90,266。
- 可用标签：30,151；exact candidate reachability=`1.0`。
- unsafe/masked 标签：3,491；exact candidate reachability=`1.0`。
- `truth_input_count=0`、`truth_derived_candidate_count=0`、`truth_feature_count=0`、`absolute_coordinate_feature_count=0`。
- candidate 双跑逐 artifact hash 一致；dataset 双跑 feature/label/fold signature 一致。

Gate 0：**PASS**。

## 5. 正式模型指标

| 指标 | seed 17 | seed 29 | seed 43 | 门槛 |
|---|---:|---:|---:|---:|
| Segment macro-F1 | 1.0000 | 1.0000 | 0.9869 | >=0.85 |
| USE_RCSD precision | 1.0000 | 1.0000 | 1.0000 | >=0.95 |
| unsafe fallback recall | 0.9963 | 0.9966 | 0.9972 | >=0.98 |
| accepted coverage | 0.3637 | 0.3589 | 0.3533 | >=0.50 |
| Movement exact | 1.0000 | 1.0000 | 1.0000 | >=0.90 |
| anomaly recall | 0.9869 | 0.9908 | 0.9918 | >=0.95 |
| anomaly precision | 0.9042 | 0.7684 | 0.7472 | >=0.80 |
| strongest non-neural Segment macro-F1 | 0.4341 | 0.4341 | 0.4341 | 神经至少 +0.03 |

Gate 1：三个 seed 均因 coverage 失败。Gate 2：seed 17 通过，seed 29/43 因 anomaly precision 失败。主 macro 极差为 `0.0131`，但 Gate 3 要求三个 seed 全部门禁通过，因此 Gate 3 失败。

## 6. 为什么 coverage 不是模型学习失败

truth-exact 对照直接使用正确 candidate、正确 anomaly target 和相同 hard gate：

- Segment、Movement、anomaly、fallback 全部为 `1.0`；
- 49 Case合法、2 Case预期失败；
- accepted coverage 仍只有 `0.36933`。

这说明当前逐对象 label 在整图组合时存在 carrier 来源不一致：独立正确的 Segment/Movement 选择，组合后仍可能出现 T01/proposal 同 ID 的真实几何、`mainnodeid` 或其它核心字段冲突，从而依法升级 Junction fallback。为了避免把扩展审计字段差异误当拓扑冲突，本轮仅将“二维几何和全部 T01 核心字段精确一致”的 payload 视为 carrier 语义等价；每 seed 共记录 1,591 次等价 coalesce，未合并或改写属性。真实核心差异仍 fallback。该修正把 seed 17 coverage 从 0.1320 提升到 0.3637，但不能跨越 0.50。

因此，继续扩大同一基础模型或增加独立对象训练轮次不能解决主要矛盾。若启动下一阶段，应先建立 JunctionUnit 级、整图一致的 carrier-set truth/candidate compatibility，再研究 joint scorer/约束选择；该建议尚未获得实施授权。

## 7. RoadGraph 与 GIS 安全

三个 seed 均为：

- 49 `LEGAL` + 2 `EXPECTED_FAIL`，非预期失败 0；
- `T10:74155468` 精确保留 `Road endpoint Node missing: 953982` 与 `953982->47348378`；
- `T10:609214532` 精确保留 `Road endpoint Node missing: 987665` 与 `987665->987661`；
- unsafe ADVANCE_RIGHT 发布 0，Junction 冲突错误替换 0；
- `skeleton_mutation_count=0`、`truth_feature_count=0`、`relaxation=false`、`content_repair=false`、`silent_fix=false`。

QGIS 3.40.14 独立审计 51 Case 的 204 个 T01/proposal Road/Node 图层，共 78,470 个 feature：CRS 全部为 `EPSG:3857`，空几何 0、非法几何 0、空图层 0。正式输出没有单独发布 GPKG，也没有冻结 road-polygon reference，因此不适用 `in_road_ratio` overlay；本轮使用 PyQGIS 图层、CRS、几何与逻辑 RoadGraph 引用/方向/拓扑联合门禁，`gate_pass=true`。

Gate 4：**PASS**。

## 8. 确定性与资源

seed 17 独立重放逐内容一致：candidate、dataset、5 个 model-state signature、5 份 score、prediction、fallback、51 个 RoadGraph 和去除运行耗时后的 metrics 全部相同。

资源：

- 参数量：3,553,074–3,553,394；
- 峰值 RSS：1,612,115,968 bytes；VRAM=0；
- 最慢 fold：125.570s；最慢 seed：414.069s；三 seed 总训练：844.244s；
- 单 Case scorer P95/max：0.404s/1.167s。

Gate 5：**PASS**。

## 9. 测试与治理

- 完整 P05 回归：140 passed。
- P05 源码/测试共 119 个 `.py` 文件；`>=60KiB=0`、`>=100KB=0`，最大为 `scheme_a_baseline.py` 58,135 bytes。
- P1 未新增或修改 `scripts/`、repo CLI、`__main__.py`、Makefile 或 T10 stage；只新增模块 callable。一次性 QGIS 审计脚本位于 `outputs/_work/`，不属于长期入口，`entrypoint-registry.md` 无需改变。

## 10. 最终门禁

- Gate 0：PASS
- Gate 1：FAIL
- Gate 2：FAIL（seed 29/43）
- Gate 3：FAIL
- Gate 4：PASS
- Gate 5：PASS

最终：**`P05_SCHEME_A_P1_MODEL_NO_GO`**。本结论证明 scorer 的对象识别能力很强，但当前逐对象 carrier truth/执行合同无法同时满足整图一致性与 50% 自动接受覆盖率；不得解释为神经网络整体不适用，也不得解释为可以进入生产。
