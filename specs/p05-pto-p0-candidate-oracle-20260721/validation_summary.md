# P05-PTO-P0 验证结论

## 1. 正式结论

PTO-P0 的候选可达性与 Oracle-cost formulation **语义门禁通过**，当前全链路成本门禁 **失败**。

- 可以进入 PTO-P1 的离线 learned-scoring 研究：使用已冻结候选训练 object-conditioned scorer，并执行业务 Case grouped 5-fold OOF。
- 不能宣称神经网络已生成最终 RoadGraph；P0 尚未训练任何 scorer。
- 不能把当前 T03-T06 全链策略重放作为在线候选生成器投入生产。PTO-P1 只能先消费冻结/缓存候选；生产化前必须另行完成增量或轻量 proposal generator，并重新通过成本门禁。

## 2. 范围与正式证据

- 数据：`E:\TestData\POC_Data`，`T10=6`、`T10-Error=25`、`T10-Error-2=20`，共 `51` Case。
- 排除：`T10-Error / 1213556_1263661`，候选/标签/求解/评价出现次数均为 `0`。
- 策略代码：标准 T10 使用 commit `4b1c496b6cd21bd0834ed3de0e076f79ee7e9eeb`；Error 家族使用 commit `96b0ea518ba486db6d72afef79e637a0fad84e93`。
- `1885118` 仅在实验输出区补充 source-path wrapper manifest；没有复制或转换业务数据，全部外部输入仍位于允许根且逐文件哈希。
- 正式 candidate run：`outputs/_work/p05_neural_road_generation/p05_pto_candidate_20260721_01`；重复 run 为 `_02`。
- 正式 solve run：`outputs/_work/p05_neural_road_generation/p05_pto_solve_20260721_05`；确定性对照 run 为 `_04`。
- 确定性审计：`outputs/_work/p05_neural_road_generation/p05_pto_determinism_audit_20260721.json`。
- GIS 审计：`outputs/_work/p05_neural_road_generation/p05_pto_gis_audit_20260721.json`。

## 3. Gate 1：候选可达性

| 指标 | 实测 | 结论 |
|---|---:|---|
| Case | `51/51` | PASS |
| truth input / truth-derived candidate | `0 / 0` | PASS |
| Road | `23,224/23,224` | PASS |
| 最终 Node | `27,553/27,553` | PASS |
| T05 Node | `24,739/24,739` | PASS |
| T05 pointer | `4,760/4,760` | PASS |
| SPLIT-derived child | `1,730/1,730` | PASS |
| 全 action coverage | `100%` | PASS |

候选共 `295,357` 个，变量 `295,357` 个，有限 component/group 与约束各 `119,064` 个，`unbounded_enumeration=false`。候选 JSONL SHA-256 为 `b4e2999c542a87ebfc392487f473d21fcd2c77c1df9575d6f5dd1bf7685105c2`。

`SPLIT-derived child=1,730` 按真值 Road 的 `t06_split_original_road_id` lineage 字段统计，其中 `1,654` 个由 `SPLIT` action 表达，`76` 个因 base 不在 Case 内由 `CREATE` action 表达。早期 `_01/_02` solve 曾误按 action 统计为 `1,654`；修正的是度量口径，候选、选择与物化逻辑没有变化。

## 4. Gate 2：Oracle-cost 与通用约束

| 指标 | 实测 | 结论 |
|---|---:|---|
| `OPTIMAL`、gap=0 | `51/51` | PASS |
| Road object F1 | 全部 `1.0` | PASS |
| Node object F1 | 全部 `1.0` | PASS |
| 属性精确 | `51/51` | PASS |
| 有向拓扑 F1 | 全部 `1.0` | PASS |
| hard failure | `0` | PASS |
| relaxation/content repair/silent fix | 全部 `false` | PASS |

求解只使用 action domain、base/ID/endpoint 引用、有限非空几何、合法生成状态与 group 唯一选择；没有调用 T03-T06 业务规则做事后修图。

## 5. 确定性、GIS 与资源

- 两轮 candidate JSONL SHA-256 完全一致；两轮 solve certificate SHA-256 均为 `c8830de26e497e9655929eada66af4b365c828654a3af324d5a86588aab76a63`。
- 51/51 Case 的 candidate、selection、normalized RoadGraph 与全部冻结指标 signature 一致。
- 102 个选中 Road/Node GPKG 与对应 truth CRS 全部一致，统一为 `EPSG:3857`；CRS conflict=`0`。
- Road/Node 几何语义与属性逐 Case 精确；有向拓扑 exact=`51/51`；没有 silent fix。
- candidate build+solve：P95=`1.489s`，max=`4.278s`，满足 `60s/300s`。
- 含登记策略 replay 的端到端：P95=`284.809s`，max=`684.902s`，不满足 `60s/300s`。
- P0 solve 进程 CPU=`112.156s`，峰值 RSS=`3,125,002,240 bytes`（约 `2.91 GiB`），无需 GPU；P0 自身资源满足门槛。
- 历史 replay 只有 wall time，总和=`5,751.192s`，没有完整 CPU time；因此 51 Case 全链 `2 CPU-hours` 不能证明通过。性能门禁已经因 P95/max 明确失败，不以缺失 CPU 证据补猜。

## 6. Success Criteria

| 条目 | 结论 | 说明 |
|---|---|---|
| SC-001 ~ SC-008 | PASS | 范围、泄漏、冻结计数、最优性、精确 RoadGraph、结构合法性与确定性全部通过 |
| SC-009 | FAIL | proposal replay P95/max 超限，且 replay CPU time 不可证明 |
| SC-010 | PASS | candidate/group/case index、lineage、cost、certificate、manifest、GPKG 与环境证据齐全 |

## 7. 工程验证

- `pytest --ignore=.venv tests/modules/p05_neural_road_generation -q`：`62 passed`。
- P05 源码与测试共 `55` 个文件，`>=100KB=0`、`>=60KiB=0`，最大仍为 `m1_dataset.py` 的 `46,059 bytes`。
- 未新增或修改 `scripts/`、repo CLI、`__main__.py`、Makefile 或 T10 stage；不需要更新 entrypoint registry。

## 8. PTO-P1 决策

**离线评分研究 GO，当前在线全链 NO-GO。**

PTO-P1 应固定使用本次 candidate contract 与冻结候选，训练 object-conditioned scorer，并以业务 Case grouped 5-fold 检验候选选择泛化；禁止使用 Oracle cost、truth geometry/ID 或策略最终选择作为推理输入。并行工程任务是把全量 T03-T06 replay 替换为缓存、增量或轻量 proposal generator，再独立重过端到端性能门。PTO-P1 未通过 OOF 前，不得把本次 Oracle 结果称为神经网络 Road 直出成功。
