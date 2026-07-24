# P05-R2 Validation Summary

## 1. 正式结论

R2 已完成三道门禁，结论为：**Gate 1 表示完备 PASS，Gate 2 模型可学习 PASS，Gate 3 grouped OOF 泛化 NO-GO**。

该结论否定的是当前 40.19M 全局 scene pooling + ordinal slot-query 基础模型，不是否定神经网络整体。Gate 1 已排除输出语言不完备，Gate 2 已排除模型完全不可学习；Gate 3 在累计 40 epoch、训练 loss 持续下降时仍无法生成 held-out RoadGraph，失败定位为缺少输出 query 与输入 Road/Node 实体之间可迁移的 object-conditioned matching。

## 2. 正式证据

| 阶段 | 不可变 run | manifest SHA-256 | 判定 |
|---|---|---|---|
| Gate 1 | `outputs/_work/p05_neural_road_generation/p05_r2_oracle_20260721_03` | `db22110952976a7586c525aca6ee101b34a8f31eb3dbb73c5a5ee4687069e09e` | PASS |
| Dataset | `outputs/_work/p05_neural_road_generation/p05_r2_dataset_20260721_01` | `01eb88ad93f1afde7bf308e76dba15af047220a04dd7e2e842645b7440aa504f` | 51 Case / 5 folds |
| Gate 2 | `outputs/_work/p05_neural_road_generation/p05_r2_gate2_20260721_05` | `cb4a154d1276592386462ebc2a9216116f17bb897fe559f760ae6afacf99810d` | PASS |
| Gate 3 | `outputs/_work/p05_neural_road_generation/p05_r2_oof_20260721_03` | `c8cd368d4d7db9624a9eaf3bb02342be8e5d24d3ed962f6cfbc457cb6c1858d4` | NO-GO |

Gate 3 run 从 `p05_r2_oof_20260721_02` 的 10 epoch checkpoint 精确 warm-start，每 fold再训练 30 epoch；完整 lineage 记录初始 checkpoint 路径和 hash。五折训练先执行 whole-case target entity guard，分别移除 `5/10/11/10/3` 个重叠 Case；因此后续 input direct/one-hop guard 对剩余训练集移除数为 `0`，不代表 guard 未执行。

## 3. Gate 1 — 表示完备

| 指标 | 结果 | 门槛 | 状态 |
|---|---:|---:|---|
| Road truth coverage | `23224/23224 = 1.0` | `>=0.999` | PASS |
| final Node truth coverage | `27553/27553 = 1.0` | `1.0` | PASS |
| T05 Node truth coverage | `24739/24739 = 1.0` | `1.0` | PASS |
| SPLIT truth coverage | `1730/1730 = 1.0` | `1.0` | PASS |
| T05 pointer coverage | `4760/4760 = 1.0` | `1.0` | PASS |
| pointer cardinality error | `0` | `0` | PASS |
| semantic exact Case | `51/51` | `51/51` | PASS |
| directed topology exact Case | `51/51` | `51/51` | PASS |

T05 pointer 的 base 是 copy-on-write 后的 `rcsdnode_out` 语义候选，不局限于 raw Node：`1353` 个选中项依赖显式生成的 T05 Node，`3061` 个来自 raw candidate，全部可表达。oracle 只执行 edit payload，没有调用 T03-T06 业务规则，也没有 silent fix。

## 3.1 Functional Requirements 核对

| FR | 状态 | 证据摘要 |
|---|---|---|
| FR-001~002 | PASS | 只消费冻结 M0/M2R lineage；范围为 `POC_Data` 登记样本并继承 approved exclusion，源码未硬编码 run/Case。 |
| FR-003、FR-007 | PASS | raw/T01 仅作 input；oracle edit/geometry 标记 `label_only=true`，input-target audit 未发现泄漏。 |
| FR-004~006 | PASS | Road/Node action domain 和 CREATE/SPLIT 显式 payload 已实现，51 Case truth coverage=`100%`。 |
| FR-008~009 | PASS | no-rule materializer 完成；T05 pointer `4760/4760` 可表达，cardinality error=`0`。 |
| FR-010~013 | PASS | T03/T04/T05/T06 必选、T07 off；task mask/权重、独立 loss/指标和 small-batch 门禁完成。 |
| FR-011 | PASS | grouped 5-fold；held-out target whole-case guard 后再执行 input direct/one-hop guard，没有目标实体跨 fold 进入训练。 |
| FR-014~016 | PASS | free/constrained 共用 logits；约束只含通用白名单；`content_repair=false`、`silent_fix=false`；最终使用冻结 evaluator。 |
| FR-017 | PASS | 四个正式 run 记录输入输出 hash、参数、seed、环境、耗时和资源；OOF checkpoint lineage 完整。 |
| FR-018 | PASS | 未修改 T01-T07 算法，未新增 CLI、root script、T10 stage、`__main__.py` 或 Makefile target。 |
| FR-019 | PASS | plan/tasks/本 summary 覆盖产品、架构、研发、测试、QA。 |
| FR-020 | PASS | CRS、拓扑、几何语义、追溯和性能五项均在本 summary 独立审计。 |

## 4. Gate 2 — 模型可学习

模型参数量 `40,189,891`。选定真实 small batch 覆盖全部 Road/final Node action，并验证 T03/T04、surface、T05 Node action、pointer、Road/Node edit、属性、端点和拓扑。

| 指标 | 结果 | 门槛 | 状态 |
|---|---:|---:|---|
| 必选 action/pointer/属性/端点指标 | `1.0` | `>=0.95` | PASS |
| T03/T04 relation | `1.0 / 1.0` | `>=0.95` | PASS |
| surface Dice | `0.99661` | `>=0.95` | PASS |
| Road F1 | `0.98333` | `>=0.98` | PASS |
| Node F1 | `1.0` | `>=0.98` | PASS |
| normalized directed topology F1 | `1.0` | `1.0` | PASS |
| structural hard failure | `0` | `0` | PASS |
| peak CUDA memory | `1,056,603,136 bytes` | `<=16GB` | PASS |

## 5. Gate 3 — grouped OOF 泛化

| SC | 指标 | 结果 | 门槛 | 状态 |
|---|---|---:|---:|---|
| SC-008 | T03 relation macro-F1 | `0.35260` | `>=0.80` | FAIL |
| SC-008 | T04 relation macro-F1 | `0.56596` | `>=0.75` | FAIL |
| SC-008 | surface Dice | `0.20409` | `>=0.80` | FAIL |
| SC-009 | T05 pointer accuracy | `0` | `>=0.90` | FAIL |
| SC-010 | Road edit macro-F1 | `0.25584` | `>=0.75` | FAIL |
| SC-010 | SPLIT recall mean | `0.33333` | `>=0.70` | FAIL |
| SC-011 | Road F1 mean / worst | `0 / 0` | `>=0.85 / >=0.70` | FAIL |
| SC-011 | keep-all baseline / delta | `0.64657 / -0.64657` | `>=+0.05` | FAIL |
| SC-012 | Node F1 mean | `0.0001223` | `>=0.90` | FAIL |
| SC-013 | topology hard-failure Case | `51/51` | `0` | FAIL |
| SC-014 | content repair / silent fix | `0 / 0` | `0 / 0` | PASS |
| SC-015 | repeat determinism | `51/51` | `51/51` | PASS |
| SC-016 | parameters | `40.19M` | `20M~50M` | PASS |
| SC-016 | peak VRAM | `6,362,636,288 bytes` | `<=16GB` | PASS |
| SC-016 | cumulative five-fold training | `651.50s` | `<=12 GPU-hours` | PASS |
| SC-016 | single-Case inference P95 | `33.92s` | `<=60s` | PASS |

free/constrained 使用同一 logits；本次没有合法性 intervention，`content_repair=false`、`silent_fix=false`。资源与确定性合格不能替代 RoadGraph 业务指标。

## 6. GIS 五项审计

- **CRS 与坐标变换**：truth layer CRS 原样继承；candidate/truth CRS 必须一致，不做隐式重投影。Gate 1 全部通过，Gate 2 为 `EPSG:3857` 一致，Gate 3 未出现以 CRS 修复掩盖失败的情况。
- **拓扑一致性**：Gate 1 为 51/51 exact，Gate 2 normalized topology F1=`1.0`；Gate 3 为 `0` 且 51/51 hard failure，如实判失败，没有 silent fix。
- **几何语义**：生成 Road 使用显式 64 点 slot geometry；任何几何 fallback 只用于评价匹配，不反向修改候选。Gate 3 Road F1=`0`，未用后处理业务修图提高指标。
- **审计可追溯性**：oracle/dataset/Gate 2/OOF manifest 均记录输入、参数、输出、环境与 hash；OOF warm-start checkpoint lineage 完整。
- **性能可验证性**：Gate 1 `64.55s`；Gate 2 峰值显存约 `0.98GiB`；Gate 3 累计训练约 `10.86min`、峰值约 `5.93GiB`、推理 P95 `33.92s`。

## 7. 五类职责结论

- **产品**：本轮回答了“现有标签是否足以验证当前方案”；现有 51 Case 足以判定当前架构 no-go，不先要求补更多 Case。
- **架构**：保留已通过的 edit/pointer 表示、通用合法性约束和 evaluator；停止 ordinal slot-query 路线，下一轮改为 object-conditioned graph/set decoder。
- **研发**：R2 callable、dataset、40.19M 网络、Gate 2 与 grouped OOF 已实现；未新增 CLI、script、T10 stage、`__main__.py` 或 Makefile target。
- **测试**：P05 全量单元测试、compileall、determinism、hash 和 code-size 审计完成。
- **QA**：51 Case 逐 Case GPKG、最差 Case、基线、拓扑、CRS、资源和 no-silent-fix 证据均已保留。

## 8. 后续决策

当前不应继续给同一 slot-query 模型增加 epoch，也不应先把“补更多人工 Case”当作前置条件。若用户启动下一轮，应建立新的 SpecKit，采用 object-conditioned set/graph decoder：输出/edit/pointer query 对输入 Road/Node 做 cross-attention 或 bipartite matching，显式使用 generated-node pointer key，并继续执行本轮相同的 Gate 1/2/3 与 grouped entity guard。生产接入仍不在范围内。
