# T01/T06 RCSD Road 归属升级验证报告

## 0. 2026-07-12 Final Topology 质量修复补充

本节是 Phase 11 的最新正式结果；下文 §1-§7 保留为修复前业务基线与历史审计。六 Case 按 `1885118 -> 605415675 -> 609214532 -> 706247 -> 74155468 -> 991176` 顺序重跑。31 个 T06 必修对象已清零，仅保留 1 条 source=2 inherited SWSD 输入叶子；`609214532` 中没有基线质量证据的 2 个二轮级联回退已经恢复。

| Case | 修复前 Segment replaced | 修复后 | 差值 | 修复前正式 fail | 修复后 | transition | attachment | hard-gate plan 回退 | accepted RCSD 边界 warn | inherited |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `1885118` | 937 | 929 | -8 | 15 | 0 | 0 | 0 | 9 | 12 | 0 |
| `605415675` | 250 | 250 | 0 | 12 | 1 | 0 | 1 | 0 | 7 | 1 |
| `609214532` | 661 | 653 | -8 | 16 | 0 | 0 | 0 | 8 | 14 | 0 |
| `706247` | 297 | 297 | 0 | 2 | 0 | 0 | 0 | 0 | 2 | 0 |
| `74155468` | 87 | 85 | -2 | 1 | 0 | 0 | 0 | 2 | 0 | 0 |
| `991176` | 133 | 133 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **合计** | **2,365** | **2,347** | **-18** | **46** | **1** | **0** | **1** | **19** | **35** | **1** |

说明：19 个 hard-gate plan 中有 18 个原本计入正式 Segment replaced，因此正式替换数净回退 18。18 个净回退 Segment 全部能回溯到基线中的正式 `segment_transition` fail：涉及 10 个 SWSD 路口节点，其中 8 个被 Patch 冲突硬阻断，1 个为多 RCSD 候选歧义，1 个 T05 relation 为 `status=1 / base_id=0` 且无 surface 证据。原先 `609214532` 第二轮回退的 `12836477_955933 / 12836489_12836477` 在基线并无正式 fail，已通过受限的 hard-gate cascade closure 恢复；该规则只消费当前回退计划、当前重建后的正式 fail、有效 T05 唯一 root、无 Patch/T04 冲突和 12m 距离门禁。35 个 accepted warn 全部逐行命中 `t06_accepted_native_boundary_node_ids`，错误端点豁免为 0。`605415675 / source=2 SWSD Road 604390558` 是唯一 inherited input，不属于 T06 引入质量问题。六 Case 的 `ownership_duplicate_count / ownership_missing_count / unresolved_exception_rcsd_road_count` 继续保持 `0 / 0 / 0`。

| Case / 基线失败节点 | 净回退 Segment | 基线原始证据 | 结论 |
|---|---:|---|---|
| `1885118 / 1885164` | 2 | T05 base 有效；incident mapped points 最大分离 `9.648m`；`blocked_by_patch_conflict` | 基线 F-RCSD 路口未最终 mainnode 收口 |
| `1885118 / 1888230` | 3 | T05 base 有效；最大分离 `7.504m`；`blocked_by_patch_conflict` | 基线 F-RCSD 路口未最终 mainnode 收口 |
| `1885118 / 62397379` | 1 | T05 base 有效；最大分离 `34.311m`；`blocked_by_patch_conflict` | 基线 F-RCSD 路口未最终 mainnode 收口 |
| `1885118 / 512303265` | 2 | 最大分离 `44.598m`；存在多个 RCSD candidate，至少一条 Segment mapping 与 T05 base 不一致 | 基线映射歧义，不能自动闭合 |
| `609214532 / 955928+955939` | 3 | 两端最大分离 `525.016m / 531.987m`；Segment `955928_955939` 两端 mapping 均偏离 T05 base；Patch 冲突 | 基线映射错误且路口未闭合 |
| `609214532 / 55196593` | 2 | 最大分离 `293.954m`；一条 mapping 与 T05 base 不一致；Patch 冲突 | 基线映射/最终 topology 质量问题 |
| `609214532 / 59602154` | 2 | 最大分离 `25.304m`；Patch 冲突 | 基线 F-RCSD 路口未最终 mainnode 收口 |
| `609214532 / 523835021` | 1 | T05 `status=1 / base_id=0`；最大分离 `32.871m`；`manual_no_surface_evidence` | 基线缺少有效锚定仍发布替换 |
| `74155468 / 1036486` | 2 | T05 base 有效；最大分离 `9.933m`；`blocked_by_patch_conflict` | 基线 F-RCSD 路口未最终 mainnode 收口 |

RCSD Road 正式指标从基线 `11,985 / 1,151,575.422m` 变为当前 `11,958 / 1,148,135.342m`，净变化 `-27 / -3,440.080m`。逐 Road 集合差异为“基线 used、当前未 used”80条，“基线未 used、当前 used”53条：

- 79条 lost Road 的旧 owner 直接属于上述18个基线质量回退 Segment。
- 剩余1条为 `74155468 / 5389250988279341`，基线 action 是 `include_connectivity`，两端挂接 `991220_1036486 / 1036486_991260`；这两个 Segment 均因节点 `1036486` 的基线正式 topology fail 回退。当前最终 F-RCSD 已不再包含该 Road 的两个 RCSD terminal node，因此二度连通组不再满足“两端可挂接”，属于基线质量回退的从属 connectivity 损失，不是无证据 Road 指标回退。
- 53条 added Road 包括48条提右 context、2条 connectivity supplement、2条普通 context 和1条新增正式 normal Segment carrier；它们均有当前 ownership action/evidence，未计入 Segment 替换增量。
- connectivity Road 分类从276增至607：342条 Road 新进入 connectivity owner、11条离开，净增331，主要是本次 multi-Segment ownership 分类显式化，不代表新增331条最终 Road。提右 RCSD Road 从672增至721，其中48条为新增 used Road，1条从 normal owner 重分类为 advance-right owner。逐 Road category transition 与 summary 六 Case全部一致，`rcsd_road_category_reconciliation_failure_count=0`。
- 80条 lost Road 中 `road_metric_loss_without_baseline_quality_evidence=0`；逐 Road 集合回算的长度差与 summary 六 Case全部一致，累计误差只来自逐 Road 毫米级舍入，`rcsd_road_length_reconciliation_failure_count=0`。逐 Road 明细位于 `outputs/_work/t06_rcsd_ownership_20260711/audit_topology_rollbacks/rcsd_road_metric_delta_raw_evidence.csv / .json`。

最新证据根：

- `outputs/_work/t06_rcsd_ownership_20260711/t06_<case>_topology_repair_final/step3_segment_replacement`
- 每个根下的 `t06_step3_surface_aware_plan_release_audit.json / t06_step3_topology_connectivity_audit.csv / t06_step3_authoritative_transition_closure_audit.csv / t06_step3_summary.json`
- 六 Case 指标对照：`specs/t01-t06-rcsd-road-ownership-20260711/evidence/final_six_case_baseline_comparison.csv`
- 逐 Segment 原始证据：`specs/t01-t06-rcsd-road-ownership-20260711/evidence/final_segment_rollback_raw_evidence.csv`
- 可重放审计脚本：`outputs/_work/t06_rcsd_ownership_20260711/audit_topology_rollback_raw.py`
- 自动重建明细：`outputs/_work/t06_rcsd_ownership_20260711/audit_topology_rollbacks/final_unique_rollback_raw_evidence.csv / .json`；脚本已校验 `metric delta=-18 / unique rollback=18 / unsupported rollback=0 / recovered false rollback=2 / unsupported RCSD Road loss=0 / Road length reconciliation failure=0 / Road category reconciliation failure=0`。

测试：hard-gate cascade / final topology 聚焦回归 `27 passed`；T06 全模块 `409 passed, 1 failed`。唯一失败为既有 Windows heartbeat 临时文件并发 `PermissionError`，单独复跑仍可稳定复现，与本次 topology 逻辑无调用关系。

## 1. 验证结论

- 六 Case 共读取 `2,484` 个 Step2 正式可替换输入，最终形成 `2,381` 个 replacement unit，成功替换 `2,347` 个。
- `16,347` 条原始 RCSD Road 全部进入唯一 ownership：used `11,958`，重复 `0`、缺失 `0`、`unresolved_exception=0`。
- 共形成 `358` 个 multi-Segment connectivity group，其中 `301` 个 used，承载 `607` 条已使用 RCSD Road；这些 Road 计入 RCSD Road 替换指标，不计入 Segment 替换指标。
- T01 共构建 `474` 个提右 Segment，当前 used `383`，承载 `721` 条 RCSD 提右 Road；提右不进入普通 Pair/Junc 锚定，由现有 Step3 提右流程处理。
- `1885118` 最终 Segment 替换数为 `929`。冻结基线 `937` 含有与新业务约束冲突的结果，因此不是无条件下限。

## 2. 六 Case 指标

| Case | Step2 输入 | 普通 plan | Segment 成功 | Segment 失败 | topology fail | RCSD Road 总数 | RCSD Road used | connectivity group | 提右 Segment/used |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `1885118` | 979 | 941 | 929 | 12 | 357 | 6,435 | 5,071 | 88 | 187 / 153 |
| `605415675` | 265 | 253 | 249 | 4 | 139 | 2,029 | 1,396 | 40 | 87 / 61 |
| `609214532` | 686 | 665 | 658 | 7 | 279 | 5,034 | 3,557 | 69 | 155 / 107 |
| `706247` | 324 | 302 | 295 | 7 | 51 | 1,664 | 1,170 | 30 | 29 / 25 |
| `74155468` | 92 | 88 | 87 | 1 | 8 | 518 | 317 | 3 | 3 / 1 |
| `991176` | 138 | 134 | 133 | 1 | 21 | 667 | 448 | 12 | 13 / 10 |
| **合计** | **2,484** | **2,383** | **2,351** | **32** | **855** | **16,347** | **11,959** | **242** | **474 / 357** |

六个 Case 的 `ownership_duplicate_count / ownership_missing_count / unresolved_exception_rcsd_road_count` 均为 `0 / 0 / 0`。

## 3. 1885118 的 937 口径收敛

冻结基线 `937` 由 `918` 个纯 RCSD 替换和 `19` 个 mixed 替换组成。按本次已确认业务边界审计：

1. 基线中有 `18` 个结果不能继续计为普通 Segment 替换：严格 2b 主干/carrier 不满足 `12` 个、path/group 超出 1V1 范围 `3` 个、视觉冲突 `2` 个、跨 Segment/路口边界冲突 `1` 个。
2. 受限后置锚定 gate 找到 `14` 个候选；候选阶段曾达到 `932` 个成功替换。
3. Step3 topology 对其中 4 个 plan 执行回退；其中 1 个候选在回退前本就未成功，因此成功数净回退 3，最终为 `929`。
4. 最终可按 `937 - 18 + 10 = 929` 复算；相对错误基线的回退有明确业务证据，不属于无证据指标下降。

被 topology gate 回退的 plan：

- `standard:12588988_523629862`
- `standard:12588988_607673517`
- `standard:1885191_506671896`
- `standard:513669474_602315321`

最终 topology fail 为 `357`，低于关闭后置 gate 的同轮严格基准 `358`，后置 gate 未引入新增普通 Segment hard fail。

## 4. 提右与普通 Segment 的隔离

- 提右 Segment 的 Road 必须全部满足 `formway & 128 != 0`。
- 提右 Segment 不进入普通 Segment 的 Pair nodes、Junc nodes 或锚定完整性判定。
- 普通 Segment 后置锚定 gate 的回退只处理普通 Segment topology fail；`advance_right_endpoint_connectivity` 继续保留在全局 topology 审计，但不得回退普通 Segment 候选。
- `609214532` 的 `949798_74295538 / advance_right_leaf_endpoint_unattached` 在冻结正式基线已存在；生成 RCSD Road id 的差异不构成新增失败。

## 5. 测试与环境

- T06 全量：`409 passed, 1 failed`。失败项为 `test_step3_heartbeat_uses_thread_local_tmp_files`，单独复跑仍为同一 Windows `PermissionError`，与本次业务改动无关。
- T06 后置锚定专项：`32 passed`。
- T01 全量：`237 passed, 5 failed`。5 个失败均为 Windows 路径分隔符或 CRLF text-bundle 差异，未改动主工作区存在同类问题；新增提右聚焦测试通过。
- T01/T06 `compileall` 通过。
- 当前工作树受治理源码/脚本/测试共 `791` 个；本轮所有新增和修改的 T01/T06 源码、脚本与测试文件均低于 100KB 硬阈值。

## 6. Step2 外 67 个旧成功对象收口

冻结基线中的 67 个“Step2 rejected、但 Step3 最终 replaced”对象已逐行关联当前 relation、ownership 与 connectivity group，结果如下：

| 根因 | 数量 | 当前处置 |
|---|---:|---|
| `junc_anchor_incomplete` | 8 | 保留 SWSD Segment；RCSD Road 按唯一 ownership 收口 |
| `required_topology_unresolved` | 5 | 保留 SWSD Segment；RCSD Road 按唯一 ownership 收口 |
| `path_group_exceeds_1v1_or_directionality_unresolved` | 54 | 禁止计普通 Segment 替换；其中满足连通补充证据的只计 RCSD Road 指标 |

处置结果：

- 43 个对象为 `retain_swsd_segment_assign_rcsd_roads_by_ownership`。
- 24 个对象为 `retain_swsd_segment_connectivity_supplement_only`。
- 基线 plan 涉及的 1,755 个 RCSD Road 引用全部找到当前唯一 owner，未收口引用为 0。
- 67 个当前 relation 均为 `retained_swsd / retained_swsd_segment`，均不再计 Segment 替换。

逐对象正式表：`specs/t01-t06-rcsd-road-ownership-20260711/evidence/six_case_outside_step2_business_closeout.csv`；运行输出副本位于 `outputs/_work/t06_rcsd_ownership_20260711/audit_six_cases/`。

## 7. 证据根目录

- 冻结基线：`E:\Work\RCSD_Topo_Poc\outputs\baselines\t10_full_96b0ea5_20260710_060735`
- `1885118`：`outputs/_work/t06_rcsd_ownership_20260711/t06_1885118_postplan_gate_v6/t06`
- 其余五 Case：`outputs/_work/t06_rcsd_ownership_20260711/t06_other5/<case>/t06`
- T01 提右升级：`outputs/_work/t06_rcsd_ownership_20260711/t01_1885118` 与 `outputs/_work/t06_rcsd_ownership_20260711/t01_other5/<case>`

## 8. 尚未完成

- 尚未刷新正式 baseline 指针，也未合并或推送分支。
- T01 源事实与接口契约本轮未获授权更新；T06 `SPEC.md / INTERFACE_CONTRACT.md` 已按授权更新。
