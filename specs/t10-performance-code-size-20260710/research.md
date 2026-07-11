# Research: T10 六用例性能与全仓体量现状

## 1. 权威基线

- 三个当前指针均指向：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_full_96b0ea5_20260710_060735`。
- Windows 已验证对应路径：`E:\Work\RCSD_Topo_Poc\outputs\baselines\t10_full_96b0ea5_20260710_060735`。
- 正式基线代码：`96b0ea518ba486db6d72afef79e637a0fad84e93`。
- 当前工作树起点：`8e4e35cd3d4a5669d77335f99067f71242a7757c`。
- 六用例：`1885118`、`605415675`、`609214532`、`706247`、`74155468`、`991176`。
- 正式完成证据：`baseline_summary.json`、`case_stage_status_baseline.csv`、`package_summary_baseline.csv` 和六个 Case 级 manifest；不能用只记录后四 Case 的 T10 顶层续跑 summary 代替。

## 2. 六用例基线性能分布

九阶段耗时合计：`3319.340s`；验收上限：`1991.604s`。

| 排名 | Stage | 六用例合计秒数 | 占比 |
|---:|---|---:|---:|
| 1 | `t03` | 1760.893 | 53.05% |
| 2 | `t04` | 582.128 | 17.54% |
| 3 | `t06_step3` | 489.921 | 14.76% |
| 4 | `t01` | 161.565 | 4.87% |
| 5 | `t06_step12` | 121.531 | 3.66% |
| 6 | `t05` | 88.540 | 2.67% |
| 7 | `t09_step12` | 69.289 | 2.09% |
| 8 | `t07` | 26.519 | 0.80% |
| 9 | `t09_step3` | 18.954 | 0.57% |

前三个热点阶段合计 `2832.942s`，占 `85.35%`。仅优化低占比阶段不足以达到整体目标；首轮动态 profiling 应围绕 T03、T04、T06 Step3 展开。

### Case 总耗时

| Case | 九阶段合计秒数 | 占六用例总耗时 |
|---|---:|---:|
| `1885118` | 1172.587 | 35.33% |
| `609214532` | 929.148 | 27.99% |
| `706247` | 476.551 | 14.36% |
| `605415675` | 405.459 | 12.21% |
| `991176` | 172.383 | 5.19% |
| `74155468` | 163.210 | 4.92% |

`1885118` 同时是最大耗时 Case 和用户指定的优先回归 Case，适合作为热点 profiling 与阶段门禁，但最终性能必须以六用例总和验收。

## 3. 基线版本与当前 main 的差异

正式基线 `96b0ea5` 之后，当前 main 合入了 T09 multi-evidence v2 业务版本。差异包含 T09 源码、测试、契约与架构文档，不是本轮性能改动。因此：

1. 正式 `96b0ea5` 基线继续提供用户确认的性能目标分母和历史业务成果。
2. 在任何优化前，必须用当前 main 建立未优化 reference run。
3. 当前 main reference 相对正式基线的差异标记为 `pre_existing_business_delta`。
4. 本轮优化的业务等价必须与当前 main reference 比较；否则会把已合入的 T09 业务变化错误归因给性能优化。

## 4. 全仓实时体量审计

初始审计口径：`git ls-files` 中扩展名为 `.py/.sh/.cmd/.ps1/.ts/.js/.bat` 的文件，字节阈值使用 `60 * 1024 = 61440`。用户于 2026-07-11 明确授权已废弃 T02 不拆分，因此最终整改验收排除 T02 源码及其测试；下列初始清单仍保留历史事实。

- 审计文件数：693。
- `>= 102400 bytes`：6。
- `>= 61440 bytes`：55。
- 其中 source：43；tests：12；scripts/tools：0。
- 另有 16 个文件位于 `[51200, 61440)` 预警区间，最终也应避免在拆分过程中跨线。

### 当前 `>= 102400 bytes` 文件

| Bytes | Path |
|---:|---|
| 1030609 | `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py` |
| 262747 | `tests/modules/t02_junction_anchor/test_virtual_intersection_poc.py` |
| 198693 | `tests/modules/t01_data_preprocess/test_step2_segment_poc.py` |
| 124157 | `src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_step4_event_interpretation.py` |
| 118378 | `tests/modules/t02_junction_anchor/test_stage4_divmerge_virtual_polygon.py` |
| 109693 | `src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_geometry_utils.py` |

### 其余当前 `>= 61440 bytes` 文件

```text
102194 src/rcsd_topo_poc/modules/t10_e2e_orchestration/case_runner.py
102076 tests/modules/t06_segment_fusion_precheck/test_step3_segment_replacement.py
102059 src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_segment_replacement.py
101663 src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_advance_right_contract.py
101577 tests/modules/t06_segment_fusion_precheck/test_replacement_plan.py
101536 src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step2_extract_rcsd_segments.py
101033 src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step3_engine.py
100980 src/rcsd_topo_poc/modules/t01_data_preprocess/step2_trunk_utils.py
100384 src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step6_geometry.py
 99579 src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/replacement_plan.py
 99397 src/rcsd_topo_poc/modules/t09_swsd_field_rule_restoration/frcsd_restriction.py
 99337 src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step4_association.py
 99062 tests/modules/p01_arm_build/test_p01_arm_build.py
 98901 src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/buffer_segment_extraction.py
 97325 src/rcsd_topo_poc/modules/t05_junction_surface_fusion/phase2_runner.py
 93889 tests/modules/t06_segment_fusion_precheck/test_runner_outputs.py
 92001 tests/modules/t10_e2e_orchestration/test_t10_contracts.py
 89959 src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_topology_connectivity_audit.py
 88779 src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_surface_topology_audit.py
 86865 src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py
 85713 src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_divmerge_virtual_polygon.py
 85327 src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_step5_geometric_support.py
 85083 src/rcsd_topo_poc/modules/t11_manual_relation_review/extract.py
 84279 tests/modules/t05_junction_surface_fusion/test_phase2_rcsd_junctionization.py
 83941 src/rcsd_topo_poc/modules/t01_data_preprocess/step1_pair_poc.py
 82602 src/rcsd_topo_poc/modules/t01_data_preprocess/step5_oneway_segment_completion.py
 82416 src/rcsd_topo_poc/modules/t01_data_preprocess/step2_segment_poc.py
 81045 src/rcsd_topo_poc/modules/p01_arm_build/final_road_next_road.py
 80397 src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/text_bundle.py
 80257 src/rcsd_topo_poc/modules/t01_data_preprocess/skill_v1.py
 80217 src/rcsd_topo_poc/modules/p01_arm_build/topology.py
 78892 src/rcsd_topo_poc/modules/t08_preprocess/nodes_type_qc.py
 77694 src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_promotions.py
 76715 src/rcsd_topo_poc/modules/t02_junction_anchor/text_bundle.py
 75743 src/rcsd_topo_poc/modules/t01_data_preprocess/step5_staged_residual_graph.py
 74915 src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_event_interpretation_core.py
 73529 src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/runner.py
 72552 src/rcsd_topo_poc/modules/t02_junction_anchor/stage3_step7_acceptance.py
 71129 src/rcsd_topo_poc/modules/t02_junction_anchor/stage2_anchor_recognition.py
 70096 tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py
 69778 src/rcsd_topo_poc/modules/t08_preprocess/complex_junction_preprocess.py
 69630 tests/modules/t06_segment_fusion_precheck/test_buffer_segment_extraction.py
 67670 src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/rcsd_unreplaced_attribution.py
 66552 src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/final_publish.py
 65601 src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_topology_supplement.py
 64985 src/rcsd_topo_poc/modules/t08_preprocess/junction_type_repair.py
 62713 src/rcsd_topo_poc/modules/t01_data_preprocess/step2_arbitration.py
 62695 src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/step3_intersection_match.py
 62155 tests/modules/t06_segment_fusion_precheck/test_step3_topology_connectivity_audit.py
```

## 5. 初步技术判断

- 性能目标需要至少从 T03 主热点获得大幅收益，并配合 T04/T06 Step3；单纯拆文件不会自动带来性能提升。
- 所有体量拆分都必须是机械职责迁移和兼容 facade，不能与性能算法改写混成不可审计的大 diff。
- 超过 100 KB 的 T02/T01 测试与 T02 源码必须先做 characterization/import coverage，再拆分；T02 为 Retired，仅做结构保持，不恢复业务开发。
- root `scripts/` 当前无 60 KB 超线文件；`scripts/t10_run_innernet_full_pipeline.sh` 为 51499 bytes，处于预警区但本轮若不触碰可保持不变。
- 当前 main 的六用例 reference、T04/T06 Step3 动态 profiling 和候选收益排序尚未完成，是 implement 前的剩余阻塞性研究任务。

## 6. 当前 main 的 `1885118` 未优化 reference

成功 run root：

`outputs/_work/t10_performance_reference/current_main_ref_1885118_8e4e35c_r2`

- 代码：`8e4e35cd3d4a5669d77335f99067f71242a7757c`
- 状态：九阶段全部 `passed`
- T10 stage duration 合计：`1259.214927s`
- `/usr/bin/time` wall-clock：`1226.74s`
- peak RSS：`564420 KB`
- 第一次 `current_main_ref_1885118_8e4e35c` 在进入业务计算前失败，原因是 Windows 创建的 worktree `.git` 指针不能被 WSL 直接识别；第二次通过显式 `GIT_DIR/GIT_WORK_TREE` 绑定同一 worktree 后成功。失败 run 不进入性能或业务 reference。

| Stage | 当前 main 秒数 | 正式基线秒数 | 当前 - 基线 |
|---|---:|---:|---:|
| `t01` | 32.918 | 45.154 | -12.236 |
| `t07` | 8.825 | 8.698 | +0.127 |
| `t03` | 771.574 | 704.572 | +67.002 |
| `t04` | 164.863 | 149.258 | +15.605 |
| `t05` | 25.111 | 25.027 | +0.084 |
| `t06_step12` | 40.043 | 37.953 | +2.090 |
| `t06_step3` | 182.457 | 170.562 | +11.895 |
| `t09_step12` | 28.061 | 26.771 | +1.290 |
| `t09_step3` | 5.364 | 4.593 | +0.771 |

单次 reference 比正式基线慢 `86.628s`，主要来自 T03 最后少数重 Case 和跨盘 I/O 波动，因此最终性能结论必须同时解释阶段内部 timer，不能只依赖单次总时长。

## 7. T03 动态 timer 结论

当前 main reference 的 T03 共执行 643 个子 Case，631 accepted、12 rejected、0 runtime failed。内部 timer：

| Timer | 秒数 | 解释 |
|---|---:|---|
| `step3` | 305.609 | 包含 Step3 几何计算和 4 个 Case 级 GPKG/JSON 输出；其细分几何 timer 合计仅约 7 秒，主要成本为输出写盘 |
| `output_write` | 380.699 | 每 Case 4 个 Step6/Step7 GPKG 加 4 个 JSON |
| `surface_candidate_write` | 83.659 | closeout 逐个重读约 631 个 accepted `step7_final_polygon.gpkg` 后汇总 |
| `case_observability_write` | 29.430 | 每 Case terminal/progress 状态写盘 |
| `local_context_snapshot_write` | 13.588 | T10 默认 `LOCAL_CONTEXT_SNAPSHOT_MODE=all` 的 internal snapshot |
| `step6` | 4.708 | Step6 几何业务计算 |
| `association` | 2.180 | Step4/5 关联业务计算 |
| `local_feature_selection` | 0.622 | shared layers 局部查询 |

结论：T03 的首要热点是大量独立小 GPKG 的创建与 closeout 重读，而不是业务几何算法。第一批低风险优化候选：

1. Step3 和 Step6/7 的独立 GPKG 写入使用有界并发，保持每个文件名、layer、schema、属性和 geometry 不变。
2. 当前新 run 在内存中保留 accepted final geometry 供 closeout 汇总，resume/retry 对历史 Case 仍从正式 Case GPKG 回退读取。
3. 保留 terminal record authoritative、所有 Case 级正式输出和 `LOCAL_CONTEXT_SNAPSHOT_MODE=all`，不通过删除审计产物换取性能。

## 8. 业务等价指纹基础设施

已新增测试辅助模块 `tests/modules/t10_e2e_orchestration/artifact_equivalence.py`，比较规则：

- JSON：忽略 duration/timestamp/run root/run id 等非业务元数据，其余递归比较。
- CSV：保留业务列，以行集合比较，避免无业务意义的输出顺序误判。
- GPKG/GeoJSON：比较 layer、CRS、schema、业务属性和 canonical WKB geometry，不比较 SQLite container timestamp/物理页布局。
- tree manifest：排除 stdout、progress、performance/perf-audit 观测文件，正式结构化产物全部纳入。

对应单元测试 `6 passed`。首次全树扫描暴露 WSL/NTFS 小文件和重复 CRS/path resolve 成本，helper 已改为直接 SQLite 读取 GPKG、缓存根路径别名、使用有界进程池并保持相对路径稳定排序。复制到 WSL 本地盘后，两个 13212 项 manifest 分别在 `9.021s` 和 `9.118s` 内完成。

## 9. 正式基线与当前 main 的业务差异隔离

完整 1885118 结构化清单均为 `13212` 项，无缺失、无新增。初始语义差异 `1159` 项，经逐键核实后：

- T01-T08 业务差异为 `0`；原差异均为 commit、时间戳、阶段耗时、临时目录、Python 路径、输入包 stat ID、容器 SHA/size 等非业务观测值。
- 剩余差异 `14` 项，全部位于 T09：T09 Step1/2 的 13 项 multi-evidence v2 产物和 T09 Step3 的 1 项汇总。
- 这 14 项与 `96b0ea5 -> 8e4e35c` 已合入的 T09 multi-evidence v2 业务提交一致，登记为 `pre_existing_business_delta`，不能作为本轮优化差异。

证据：

- `outputs/_work/t10_performance_analysis/current_main_ref_1885118_8e4e35c_r2/baseline_manifest.json`
- `outputs/_work/t10_performance_analysis/current_main_ref_1885118_8e4e35c_r2/current_manifest.json`
- `outputs/_work/t10_performance_analysis/current_main_ref_1885118_8e4e35c_r2/comparison_refined_v2.json`

## 10. 当前 main 六用例未优化 reference

run root：`outputs/_work/t10_performance_reference/current_main_ref_6cases_8e4e35c`

- 六个 Case 全部 `passed`，54 个 stage record 全部 `passed`。
- stage duration 合计 `3668.089s`，为正式基线 `3319.338s` 的 `110.51%`。
- `/usr/bin/time` wall-clock 为 `1:00:36`，peak RSS `565752 KB`。
- 正式目标仍为 stage duration 合计 `<= 1991.603s`；相对当前 main reference 需要减少至少 `1676.486s`。

| Stage | 当前 main 秒数 | 正式基线秒数 | 当前占比 |
|---|---:|---:|---:|
| T03 | 1939.347 | 1760.893 | 52.87% |
| T04 | 671.577 | 582.128 | 18.31% |
| T06 Step3 | 552.624 | 489.921 | 15.07% |
| T06 Step1/2 | 146.327 | 121.531 | 3.99% |
| T01 | 114.165 | 161.565 | 3.11% |
| T05 | 100.825 | 88.540 | 2.75% |
| T09 Step1/2 | 84.937 | 69.289 | 2.32% |
| T07 | 32.780 | 26.519 | 0.89% |
| T09 Step3 | 25.507 | 18.954 | 0.70% |

前三个阶段合计 `3163.548s`，占当前 reference 的 `86.25%`，必须作为第一性能阶段。

## 11. T04 与 T06 动态 profile

T04 1885118 的 `160.074s` 内部运行中，87 个 Case 的 timer 汇总：

- `step5_7_output_write = 122.651s`（约 76.6%）
- `step1_4 = 21.219s`
- `local_feature_selection = 0.339s`
- `same_case_resolution = 0.163s`

T06 Step3 使用相同 1885118 输入在独立输出根运行 `cProfile`：`630130197` 次函数调用，profile wall `303.70s`。主要累计热点：

- 两轮 `_run_step3 = 124.443s`、两轮 `_run_surface = 144.263s`。
- 8 次 topology connectivity audit `82.424s`。
- 53372 次 `_segment_uncovered_metrics` `53.683s`，其中 50432 次 Shapely `buffer` 自身耗时 `53.213s`。
- 55 次 `write_feature_triplet = 88.290s`，其中 GPKG 写入累计 `60.339s`。
- 64 次 `read_vector_layer = 59.951s`。

证据：`outputs/_work/t10_performance_profiles/t06_step3_1885118/t06_step3_1885118.prof`、`top_cumulative.txt`、`top_self_time.txt`。

## 12. 优化候选排序

1. **P0 T03 独立输出并发 + closeout 复用 geometry**：Step3/Step6/Step7 的独立 GPKG/JSON 以有界线程并发，保留所有文件、layer、schema、属性和 WKB；新鲜 Case 的 final geometry 直接传给 closeout，resume/retry 缺失时回退正式 GPKG。验证：T03 单测、1885118 完整结构化等价、timer 和 stage duration。
2. **P0 T04 Case 输出并发**：只并发同一 Case 内彼此独立的 JSON/GPKG 写入，不并发业务决策，不改变文件名或 batch closeout。验证：T04 characterization、1885118 T04 全产物等价和 87 Case 终态一致。
3. **P1 T06 topology coverage cache 跨重复 audit 复用**：把现有内容寻址 `CoverageCacheKey` 的 cache 生命周期从单次 audit 扩展到同一 Step3 pipeline，key 已包含 buffer、source、road id 和 geometry digest，命中返回相同 Shapely geometry。验证：T06 topology/audit tests、1885118 Step3 全产物等价和 cProfile buffer 次数下降。
4. **P1 T06 输出与输入 I/O 收敛**：复用已加载 feature collections，并仅对独立正式文件做有界写入并发；不减少两轮 Step3/surface、审计行或正式输出。验证：T06 完整模块测试与 1885118。
5. **P2 体量拆分**：所有超 60 KB 文件使用兼容 facade + 内部职责模块机械拆分；与性能逻辑分批提交和验证，避免将语义变更混入结构迁移。

## 13. T03 P0 首批优化结果

实现：

- Step3 的 4 个 GPKG + 2 个 JSON 使用最多 4 线程有界并发。
- Step6/7 的 4 个 GPKG + 4 个 JSON 使用最多 4 线程有界并发。
- 当前新鲜 Case 的 final polygon geometry 直接供 closeout 汇总；resume/retry 或历史 Case 继续从正式 GPKG 回退。

验证：

- T03 模块测试 `234 passed`。
- 1885118 九阶段全部 `passed`。
- T03 从同次六用例 current-main reference 的 `795.981s` 降至 `538.682s`，下降 `257.300s / 32.3%`。
- `surface_candidate_write` 从约 `83.659s` 降至 `8.235s`。
- 1885118 九阶段合计从 `1311.123s` 降至 `1155.005s`；其他阶段本次合计出现约 101 秒波动。
- 完整结构化清单两侧均 `13209` 项，无缺失、无新增、业务差异 `0`。

证据：

- `outputs/_work/t10_performance_candidates/t03_parallel_output_v1_1885118`
- `outputs/_work/t10_performance_analysis/t03_parallel_output_v1_1885118/stage_comparison.json`
- `outputs/_work/t10_performance_analysis/t03_parallel_output_v1_1885118/comparison_refined.json`

## 14. 60KB 架构收敛完成后的 `1885118` 门禁

run root：`outputs/_work/t10_performance_candidates/t10_codesize_complete_1885118_20260711`

- 九阶段全部 `passed`，runner wall-clock `1036.002s`，九阶段 duration 合计 `1024.492s`。
- T03 完成 643/643 个子 Case，`631 accepted / 12 rejected`，与 reference 终态计数一致。
- 与 Phase3-5 候选直接比较：`13209 / 13209` 个结构化工件，missing/extra/changed 均为 `0`。
- 与同业务版本 current-main reference 直接比较：`13209 / 13209` 个结构化工件，missing/extra/changed 均为 `0`。
- 阶段耗时：T01 `36.325s`、T07 `9.984s`、T03 `480.909s`、T04 `139.627s`、T05 `35.146s`、T06 Step1/2 `56.048s`、T06 Step3 `221.880s`、T09 Step1/2 `37.863s`、T09 Step3 `6.710s`。
- 与 current-main 同 Case `1259.215s` 相比下降 `18.64%`；该单 Case 仍不能代替六用例正式性能验收。

## 15. 最终正式回归结果（2026-07-11）

- 正式候选根：`outputs/_work/t10_performance_candidates/t10_scratch_formal6_v31/t10`。
- 执行顺序严格为 `1885118 -> 605415675 -> 609214532 -> 706247 -> 74155468 -> 991176`；六个 Case 均为 `passed`，每例九阶段均通过。
- 六例九阶段 `duration_seconds` 合计 `1944.274435s`，为正式基线 `3319.338429s` 的 `58.574%`，低于验收上限 `1991.603057s` 共 `47.329s`。
- 相对基线耗时下降 `41.426%`；按同一工作量换算，吞吐能力提升 `70.724%`。
- 现有 wrapper 的外层真实墙钟（含 scratch 发布与清理）为 `1869.07s`。发布器内部另记录 `58.910666s` 发布耗时；该值作为运维观测保留，不并入 spec 明确规定的九阶段性能验收口径。

| Stage | 正式基线秒数 | 最终候选秒数 | 变化秒数 |
|---|---:|---:|---:|
| `t03` | 1760.893 | 782.602 | -978.291 |
| `t04` | 582.128 | 295.962 | -286.166 |
| `t06_step3` | 489.921 | 415.858 | -74.063 |
| `t01` | 161.565 | 116.051 | -45.514 |
| `t06_step12` | 121.531 | 148.385 | +26.854 |
| `t05` | 88.540 | 36.267 | -52.273 |
| `t09_step12` | 69.289 | 88.412 | +19.123 |
| `t07` | 26.519 | 35.240 | +8.721 |
| `t09_step3` | 18.954 | 25.497 | +6.543 |
| **总计** | **3319.338** | **1944.274** | **-1375.064** |

### 业务等价与 GIS/QA 证据

- current-main 架构 reference：`outputs/_work/t10_performance_candidates/t10_codesize_complete_6cases_20260711`。
- reference 与候选各发现 `36731` 个结构化 CSV/JSON/GPKG/GeoJSON 工件；最终比较 `missing=0`、`extra=0`、`changed=0`。
- 比较器逐层核验 GPKG/GeoJSON 的 CRS、schema、属性与几何 WKB；几何只在比较阶段使用 `1e-7 m` 规范化浮点噪声，生产输出未做 silent fix。
- `rcsd_road_ids`、`frcsd_road_ids` 是成员集合字段，仅这两个字段忽略排列顺序；路径序列与其余列表仍顺序敏感。用例 `609214532` 曾发现两个相同成员的排列反转，按该明确语义复核后四个关联 CSV/GPKG 工件均一致。
- 正式 stage JSON、顶层 manifest/summary、文件数/字节数发布核验和 scratch 清理状态共同提供输入、参数、输出、运行环境与性能追溯。

### 最终测试与体量门禁

- `pytest -q --import-mode=importlib tests --ignore-glob='*t02*'`：`1526 passed, 4 failed`；4 个失败全部位于 T04 真实 Anchor_2/ledger 既有回归，并在未修改主仓库以相同断言原样复现 `4 failed`，不是本轮引入。
- 等价比较器专项：`9 passed`；本轮其他模块专项测试见 tasks 各 Phase 记录。
- 工作树实时扫描 `780` 个受治理文件；排除用户授权的 `11` 个 Retired T02 文件后，`>= 61440 bytes = 0`。
