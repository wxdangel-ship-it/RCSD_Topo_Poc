# 当前超阈值代码 / 脚本文件审计

## 范围

- 主审计日期：2026-06-12；T09 增量审计：2026-07-10；T10 性能与 60KB 治理增量审计：2026-07-11；T01/T06 ownership 增量审计：2026-07-12；T10 增加 T11 工作流增量审计：2026-07-13；T06 性能恢复与 Step3 修复性拆分增量审计：2026-07-14；T06 全量性能恢复增量审计：2026-07-16；T12 F-RCSD 质检、T10 可选接入及专用流水线增量审计：2026-07-18；T12 reviewed resume 与 false-positive hardening 增量审计：2026-07-19
- 阈值：单文件超过 `100 KB`
- 口径：按 `code-boundaries-and-entrypoints.md`，审计纳入版本管理的 `src/`、`scripts/`、`tests/`、`tools/` 下源码 / 脚本文件。
- 本表只记录结构债事实，不代表本轮进入对应模块正文治理。
- 用户于 2026-07-11 明确确认 T02 已废弃并授权本轮不拆分；T02 超线文件继续登记为结构债，但从本轮 60KB 收敛验收中排除，且本轮未触碰 T02 源码或测试。
- 2026-07-13 T10 增加 T11 工作流后的 Windows worktree 扫描确认：除下列 Retired T02 文件外，`>= 61440 bytes` 文件仍仅为 `step2_trunk_utils.py`（`62004` bytes）与 `step3_surface_aware_plan_release.py`（`74453` bytes），均低于 100KB 硬阈值且本轮未触碰；本轮修改的 9 个源码/脚本/测试文件全部低于 60KiB，最大为 `case_runner_pipeline.py`（`58855` bytes）。Final topology gate 已拆至 `step3_final_topology_gate.py`（`9687` bytes），hard-gate 级联 transition 收口已拆至 `step3_authoritative_transition_closure.py`（`14812` bytes）；主编排文件仍低于 100KB。
- 2026-07-14 T06 性能恢复轮次将 `step3_surface_aware_plan_release.py` 的 surface release 决策、输入索引与计划行构建职责拆至 `step3_surface_release_plan.py`；完成验证态审计传递与最终发布收口后，主编排文件为 `57187` bytes，新模块为 `19639` bytes，二者均低于 60KiB 安全线，既有正式入口与调用签名保持不变。本轮扫描 T06 的 `src/` 与 `tests/` 共 `153` 个源码/脚本文件，`>= 61440 bytes` 为 `0`。
- 2026-07-16 T06 全量性能恢复轮次发现后续回归新增用例使 `test_replacement_plan.py` 漂移到 `63163` bytes；已将末尾两个独立 risk-marker 用例迁移至 `test_replacement_plan_risk_markers.py`。拆分后原文件 `60142` bytes、新文件 `3534` bytes；新增 validation runtime / deferred final publish、deferred hard-gate plan、拓扑审计内存复用、ID 解析及内网验收包测试后，T06 `src/` 与 `tests/` 共 `160` 个源码/脚本文件，另有 `2` 个既有 `scripts/t06*` 脚本，核心合计 `162` 个；SpecKit 下另有 `3` 个一次性内网验收脚本，纳入体量扫描后总计 `165` 个，`>= 61440 bytes` 为 `0`。当前 T06 最大文件为本轮修改源码 `step3_surface_aware_plan_release.py`（`60870` bytes），其次为既有 `test_step3_surface_topology_audit.py`（`60787` bytes），均低于 60KiB。除 Retired T02 外仍只有本轮未触碰的 T01 `step2_trunk_utils.py` 超过 60KiB，作为既有治理缺口继续登记；正式入口和调用签名不变，一次性验收工件不登记为官方入口。
- 2026-07-18 T12 F-RCSD 质检轮次扫描全部 `29` 个新增/修改源码、脚本和测试：均低于 100KB 硬阈值；T12 模块最大文件为 `candidate_audit.py`（`15895` bytes），正式入口 `t12_run_frcsd_quality_audit.py` 为 `3899` bytes；两个 SpecKit 一次性 validation 脚本最大为 `validate_1026960.py`（`11717` bytes），不登记为官方入口。T10 可选接入后最大修改文件为 `t10_run_innernet_full_pipeline.sh`（`61439` bytes，低于 60KiB `61440` bytes），其次为 `case_runner_pipeline.py`（`60207` bytes）；T12 adapter 独立放在 `case_runner_t12.py`（`5070` bytes），未回填 case runner 主流程。T06 源码、契约和入口未修改。仓库级 `>=100KB` 仍仅为本轮未触碰的 Retired T02 历史文件。
- 2026-07-18 T10 F-RCSD 专用流水线最终联合扫描 `31` 个新增/修改源码、脚本和测试：`>=100KB` 为 `0`；最大为 `t10_run_innernet_full_pipeline.sh`（`62094` bytes），因增加 T11/T12 顺序、resume/manifest 和显式 `T12_CASE_MANIFEST` 转发而超过 60KiB 软预警线，但仍低于 100KB 硬阈值。新增正式入口 `t10_run_frcsd_quality_pipeline.sh` 为 `2351` bytes，入口测试为 `2648` bytes，`case_runner.py` 为 `49048` bytes；T06 源码、契约和入口未修改，仓库级 `>=100KB` 集合不变。后续 full runner 继续增长前应拆分 stage helper，不得回填模块算法。
- 2026-07-19 T12 reviewed resume 轮次修改 `2` 个既有脚本和 `2` 个入口契约测试：`t10_run_innernet_full_pipeline.sh` 为 `64067` bytes，`t10_run_frcsd_quality_pipeline.sh` 为 `2696` bytes，两个测试分别为 `8104` 与 `3237` bytes，均低于 100KB 硬阈值。full runner 已超过 60KiB 软预警线，本轮仅修复显式新 `T12_RUN_ID` 的 run-root/manifest 选择、失败恢复一致性与复核输入优先级，未增加算法职责；后续增长前仍须拆分 stage helper。
- 2026-07-19 T12 false-positive hardening 轮次扫描全部 `14` 个新增/修改源码、测试和 SpecKit validation 脚本：`>=100KB` 为 `0`；最大为 `candidate_audit.py`（`23435` bytes），新拆出的 `semantic_carrier.py` 为 `8348` bytes，最大一次性 validation 脚本 `analyze_alias_transitions.py` 为 `15836` bytes。正式入口、CLI 参数和 T10 阶段顺序均未改变；新增 semantic helper 只承接 portal-constrained carrier 的端点与内部 alias 门禁，不回填 candidate 主编排。

## 结果

| 路径 | 体量 | 当前判断 | 建议 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py` | `1030609` bytes | 远超阈值，已构成显著结构债 | 本轮仅刷新审计；后续若继续触碰，需附拆分计划或豁免说明 |
| `tests/modules/t02_junction_anchor/test_virtual_intersection_poc.py` | `262747` bytes | 测试文件超阈值 | 后续若继续扩写，需附拆分计划、夹具下沉或按阶段拆分说明 |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_step4_event_interpretation.py` | `124157` bytes | T02 Stage4 event interpretation 文件超阈值 | 后续若继续触碰，需先拆分 Step4 interpretation / candidate helper / audit 输出职责或附豁免说明 |
| `tests/modules/t02_junction_anchor/test_stage4_divmerge_virtual_polygon.py` | `118378` bytes | T02 Stage4 集成测试超阈值 | 后续若继续扩写，需按场景拆分测试文件或下沉共享 fixture |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_geometry_utils.py` | `109693` bytes | T02 Stage4 geometry helper 超阈值 | 后续若继续触碰，需拆分 geometry primitive / topology helper / vector export 职责 |

## 未超阈值高风险预警

| 路径 | 体量 | 当前判断 | 建议 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_divmerge_virtual_polygon.py` | `85713` bytes | T02 Stage4 脚本当前低于硬阈值但仍偏大，历史审计记录已刷新 | 后续若继续触碰，需附拆分计划或豁免说明 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_kernel.py` | `56445` bytes | Step4 runtime kernel 仍承接 final event interpretation 主流程，低于硬阈值但偏大 | 后续若扩展 kernel 主流程，优先拆 multibranch / event-interpretation orchestration |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_rcsd_selection_support.py` | `53259` bytes | RCSD selection support 聚合 semantic group、local/aggregated unit 与 role mapping 支撑逻辑；RCSD trace 只允许 degree-2 passthrough | 后续扩展 RCSD 选择支撑前先评估 local-unit / aggregated-unit helper 拆分 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly.py` | `49351` bytes | T-01 已拆出 raster/path helper，主 assembly 文件降至 50 KB 以下 | 后续继续保持主流程不回填低层 raster/path helper |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_geometry_base.py` | `48003` bytes | 原 `_runtime_step4_geometry_reference.py` 已改名为 geometry base，低于阈值 | 后续避免重新引入 `reference` 命名误导 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/outputs.py` | `48524` bytes | T04 输出层新增 arbiter ledger / decision trace / review index 字段后接近 50 KB | 后续新增输出字段前优先拆 review-index writer / audit writer helper |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_event_interpretation_unit_preparation.py` | `41565` bytes | Round 2 新拆出的 unit preparation / pair-local materialization 模块 | 后续仅承接 preparation 与 scope materialization，不承接 candidate selection |
| `src/rcsd_topo_poc/modules/p01_arm_build/final_arm_validation.py` | `53011` bytes | FinalArm relaxed reverse / supplemental trace validation 实现 | 后续若继续扩展 validation 分支，优先拆 validation builder 与 evidence helper |
| `src/rcsd_topo_poc/modules/p01_arm_build/review.py` | `52972` bytes | P01 retained audit PNG / review GPKG 图层 helper | 后续 review 输出扩展先评估 layer builder / png renderer 拆分 |

## 本轮授权排除的 Retired T02 60KB 结构债快照

以下 11 个 tracked 文件为 2026-07-11 实时扫描结果。它们因用户明确授权不拆分而不进入本轮 60KB 通过计数，但仍保留结构债登记；本轮未写入这些文件。

| 路径 | 当前体量 |
|---|---:|
| `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py` | `1030609` bytes |
| `tests/modules/t02_junction_anchor/test_virtual_intersection_poc.py` | `262747` bytes |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_step4_event_interpretation.py` | `124157` bytes |
| `tests/modules/t02_junction_anchor/test_stage4_divmerge_virtual_polygon.py` | `118378` bytes |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_geometry_utils.py` | `109693` bytes |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_full_input_poc.py` | `86865` bytes |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_divmerge_virtual_polygon.py` | `85713` bytes |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_step5_geometric_support.py` | `85327` bytes |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/text_bundle.py` | `76715` bytes |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/stage3_step7_acceptance.py` | `72552` bytes |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/stage2_anchor_recognition.py` | `71129` bytes |

## 本轮已拆分降险记录

| 原路径 / 新模块 | 体量 | 当前判断 | 建议 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step3_engine.py` | `101033 -> 36056` bytes | T10 性能治理中保留 Step3 public API、graph/dijkstra monkeypatch 点、reachable cache 与主编排；geometry/status 支撑已下沉 | 保持 graph 可测试替换点与主状态编排，不回填基础几何 helper |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step3_engine_support.py` | `47907` bytes | 新拆出的 Step3 mask、single-sided、foreign object、containment 与状态构建支撑 | 达到 50KB 前继续按 mask/status 职责拆分 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step3_engine_primitives.py` | `20730` bytes | 新拆出的 Step3 geometry/vector/road primitive 与默认审计字段 helper | 保持无 Case 主编排职责 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step3_engine_models.py` | `984` bytes | 新拆出的 reachable-road cache 内部模型 | 保持仅定义 dataclass |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step6_geometry.py` | `100384 -> 26180` bytes | 保留 Step6 directional-cut、single-sided trace monkeypatch 点与兼容 public API；正式 build/status 通过惰性 wrapper 调用 runner | 保持测试替换点和兼容签名，不回填主几何编排 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step6_geometry_runner.py` | `43403` bytes | 新拆出的 Step6 正式 geometry build 与 status 编排 | 保持只承接 Step6 主流程；达到 50KB 前再拆 summary/result 分支 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step6_geometry_primitives.py` | `26733` bytes | 新拆出的 geometry、buffer、coverage、shape metric 与缓存 primitive | 保持无 Case 主编排职责 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step6_geometry_context.py` | `13680` bytes | 新拆出的 required node/road、semantic member 与 allowed-space context helper | 保持 context 选择职责 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step6_geometry_models.py` | `4229` bytes | 新拆出的 directional/cache 内部 dataclass | 保持仅定义模型 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step4_association.py` | `99337 -> 247` bytes | 已降为兼容 facade，保留 association case/status 两个既有 public callable | 禁止回填实现 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step4_association_runner.py` | `42239` bytes | 新拆出的 Step4 association 正式主编排 | 保持只承接 Case 结果编排 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step4_association_uturn.py` | `25703` bytes | 新拆出的 U-turn、degree-2 chain 与 related-scope 支撑 | 保持 U-turn/chain 职责 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step4_association_gates.py` | `23466` bytes | 新拆出的 required-node gate、support fragment、failure/status helper | 保持 gate 与 fragment 职责 |
| `src/rcsd_topo_poc/modules/t03_virtual_junction_anchor/step4_association_primitives.py` | `14747` bytes | 新拆出的 geometry、direction、group 与 corridor primitive | 保持无 Case 主编排职责 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding.py` | `5617` bytes | 已降为 road-surface fork binding facade，保留原 public entrypoint；本轮仅接入 complex SWSD shared RCSDRoad policy | 后续策略扩展优先落到对应 policy 模块，不回填 facade |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_swsd_rcsdroad.py` | `20445` bytes | 新增的 complex SWSD shared RCSDRoad fallback policy，负责无主证据复杂路口整体唯一 RCSDRoad 对齐 | 保持只承接 shared RCSDRoad 消歧与审计更新，不回填 facade |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_promotions.py` | `77694 -> 1010` bytes | 已降为 promotion policy 兼容 facade，保留既有私有 callable 导入面 | 禁止回填实现；按 base / relaxed / partial policy 继续维护 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_promotion_base.py` | `20478` bytes | 新拆出的基础 promotion context、surface 与 junction-window 公共支撑 | 保持公共支撑职责，不承接 relaxed / partial 策略主流程 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_promotion_relaxed.py` | `29846` bytes | 新拆出的 relaxed positive RCSD / junction-window promotion 策略 | 保持 relaxed promotion 与对应审计更新职责 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_promotion_partial.py` | `30959` bytes | 新拆出的 selected-surface partial support promotion 策略 | 保持 partial support 策略与对应审计更新职责 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_event_interpretation_core.py` | `74915 -> 8166` bytes | 已降为 Step4 event interpretation 兼容 facade；保留 `_prepare_unit_inputs` 及 slice-diagnostic monkeypatch 点 | 禁止回填 context、candidate pool 或 result materialization 实现 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_event_interpretation_context.py` | `27710` bytes | 新拆出的 unit context、几何参考、候选摘要与 materialization 公共支撑 | 保持上下文与基础几何职责，不承接候选池或结果编排 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_event_interpretation_candidates.py` | `18461` bytes | 新拆出的 candidate pool 与 unit envelope 构建逻辑 | 保持候选枚举与 envelope 职责 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_event_interpretation_results.py` | `32105` bytes | 新拆出的 interpretation 结果组装、candidate evaluation 与空摘要逻辑 | 保持结果物化与评估职责，达到 50KB 前再次评估拆分 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/final_publish.py` | `66552 -> 52112` bytes | Step7 单 Case 工件、发布审计与兼容 batch callable 保留在主模块 | 后续保持单 Case 物化职责，不回填 batch 输出编排 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/final_publish_batch.py` | `18743` bytes | 新拆出的 Step7 batch 图层、摘要、relation evidence 与一致性报告发布逻辑 | 保持批量输出和一致性报告职责 |
| `tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py` | `70096 -> 55408` bytes | 保留 Step7 基础发布与 legacy / official baseline 场景回归 | 新增 RCSD 专项真实 Case 回归进入独立测试文件 |
| `tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish_rcsd_cases.py` | `19442` bytes | 新拆出的 new6 user audit 与 RCSD junction 专项真实 Case 回归 | 保持 RCSD 专项场景职责，公共 fixture 继续复用既有 support 模块 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_cleanup.py` | `20057` bytes | 新拆出的 structure-only retention 与 unbound cleanup policy 模块 | 保持只承接清理 / 保留策略 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_recovery.py` | `16698` bytes | 新拆出的 road-surface recovery policy 模块 | 保持只承接 invalid-divstrip 后的 surface recovery |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_divstrip.py` | `14210` bytes | 新拆出的 divstrip-primary restore policy 模块 | 保持只承接 divstrip 优先级恢复与歧义消解 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/support_domain.py` | `569` bytes | 已降为 Step5 support-domain facade，保留原 public import surface | 后续 Step5 扩展不得回填 facade |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/support_domain_models.py` | `24848` bytes | 新拆出的 Step5 result dataclass 与 vector export，含 negative mask channel 与 positive RCSD support corridor 状态输出 | 后续 vector export 如继续增长，可单独下沉 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/support_domain_common.py` | `22931` bytes | 新拆出的 Step5 geometry / axis / scenario common helper | 保持无 case orchestration 职责 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly_models.py` | `12704` bytes | 新拆出的 Step6 result dataclass 与状态 / 审计序列化模型，含 bridge negative mask、case alignment review、relief constraint audit 与 barrier-separated 字段 | 保持只承接 Step6 结果模型，不回填 assembly 算法 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly_guards.py` | `4044` bytes | 新拆出的 Step6 guard context 与场景派生逻辑 | 保持只承接 Step6 guard 上下文，不回填 raster assembly 或 relief 算法 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly_relief.py` | `5663` bytes | 新拆出的 Step6 dominant component / cut-sliver / hole relief helper | 保持只承接不依赖 raster 主流程状态的 relief helper |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly.py` | `49351` bytes | T-01 降为 Step6 assembly 主流程与兼容导出面 | 后续 raster/path helper 不回填主文件 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly_path.py` | `29066` bytes | T-01 新拆出的 Step6 path / post-cleanup / audit helper | 保持几何约束与审计 helper，不承接主 assembly orchestration |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly_raster.py` | `10103` bytes | T-01 新拆出的 Step6 raster / connectivity helper 与常量 | 保持 raster/pathfinding helper，不承接 Step6 result 组装 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_types_io.py` | `162` bytes | T-01 降为 types/io 兼容 facade，保留旧 import surface | 后续不回填类型或 IO 实现 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_types.py` | `37941` bytes | T-01 新拆出的 runtime dataclass / constants / raster-render primitives | 后续新增类型前先评估继续拆分 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_io.py` | `38966` bytes | T-01 新拆出的 layer loading / spatial cache / branch IO helper | 后续 IO 扩展优先保持在该文件或进一步下沉 cache helper |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_kernel_base.py` | `31715` bytes | T-01 降为 Step4 kernel base 主体，几何候选物化已下沉 | 后续 kernel base 语义扩展前评估局部拆分 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_kernel_geometry.py` | `34889` bytes | T-01 新拆出的 Step4 kernel geometry / reference-candidate helper | 保持只承接几何候选物化与 reference candidate helper |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_geometry_core.py` | `35839` bytes | T-01 降为 Step4 geometry core 主体，常量与基础 helper 已下沉 | 后续 geometry core 扩展前评估局部拆分 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_geometry_constants.py` | `29487` bytes | T-01 新拆出的 Step4 geometry constants / low-level helper | 保持常量、基础分支选择与轴向 helper，不承接主 geometry orchestration |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_rcsd_anchored_reverse.py` | `24566` bytes | T-01 降为 anchored reverse 主流程与兼容导出面 | 后续 reverse policy / graph helper 不回填主文件 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_rcsd_anchored_reverse_policy.py` | `23448` bytes | T-01 新拆出的 anchored reverse evidence / policy helper | 保持 reverse evidence recovery 与基础 policy helper |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_rcsd_anchored_reverse_graph.py` | `12796` bytes | T-01 新拆出的 anchored reverse graph / conflict helper | 保持 shortest path、terminal continuation 与 conflict helper |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step2_special_junctions.py` | `11229` bytes | 新拆出的 Step2 special junction group gate、RCSD semantic/internal road coverage 与 graph edge helper | 保持只承接特殊路口组门控、RCSD graph/coverage 准备与审计，不承接 buffer extraction 主流程 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/group_replacement_audit.py` | `24264` bytes | Step2 group replacement 审计 helper，识别 rejected Segment 的 RCSD 图路径是否跨越外部 accepted SWSD anchor，输出 incident closure / path corridor 闭包状态，并对 path-corridor group union 执行正式 extractor probe | 保持只承接 group closure 与正式 probe 审计，不直接改写 replaceable |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_group_replacement.py` | `18045` bytes | Step3 path-corridor group replacement 消费 helper，新增成员级 Road 归属过滤与 standard ready 成员优先保护，避免 group union 直接污染成员 Segment relation | 保持只承接 group audit / replacement plan 到 Step3 assignment 的解析、分组与成员级作用域过滤，不承接 Road/Node 删除和 F-RCSD 输出 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_segment_replacement.py` | `546` bytes | T10 性能治理中已降为兼容 facade，保留原正式函数、模型、`T06Step3Artifacts` 与既有私有测试导入 | 禁止回填实现；正式编排只进入 runner，模型与 helper 分别进入已拆模块 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_segment_replacement_runner.py` | `42673` bytes | 新拆出的 Step3 正式编排与汇总发布主流程，低于 60KB 安全线 | 保持只承接运行编排，不回填 relation/junction/primitive 实现 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_surface_aware_plan_release.py` | `74453 -> 57187` bytes | 保留 Surface-aware Step3 运行编排、验证回滚、final topology gate、验证态审计传递与最终审计汇总；既有 callable 与参数保持不变 | 已低于 60KiB；禁止回填 release decision、输入索引或计划行构建职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_surface_release_plan.py` | `19639` bytes | 新拆出的 surface release 常量、候选决策、输入索引、计划行构建与既有私有 helper 兼容导出 | 保持纯计划决策与读取支撑职责，不承接 Step3 执行和输出发布 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_replacement_relation_support.py` | `37013` bytes | 新拆出的 junction rebuild、F-RCSD 构建、Segment relation 与 node-map 支撑 | 保持 relation/junction 职责；达到 50KB 前再次拆分 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_replacement_unit_support.py` | `25959` bytes | 新拆出的 replacement unit、特殊路口组、拓扑 supplement 与 corridor 支撑 | 不承接输出发布或 summary 编排 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_replacement_primitives.py` | `8814` bytes | 新拆出的 ID、端点、序列化与长度 primitive | 保持无业务流程编排 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_replacement_models.py` | `2102` bytes | 新拆出的 Step3 dataclass 模型 | 保持仅定义稳定内部模型 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/parallel_output.py` | `1366` bytes | Step3 独立 feature-triplet 发布器；实测 Fiona/GPKG 并发存在磁盘争用，正式编排默认确定性串行，每个工件仍走原 `write_feature_triplet` | 保留显式并发能力仅供受控测试，不改变 schema、字段或几何语义 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_topology_connectivity_audit.py` | `93342 -> 24749` bytes | 保留 topology connectivity 正式入口、基础完整性行、final topology 标注与汇总；兼容原私有 helper 导入面 | 保持正式入口与汇总职责，不回填分层 row builder 或 coverage primitive |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_topology_connectivity_rows.py` | `45730` bytes | 新拆出的 Segment internal / road / junction / retained endpoint / patch attachment 审计行构建，并透传 final topology 字段 | 达到 50KB 前按 Segment 与 patch 职责再次评估拆分 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_final_topology_metric.py` | `6687` bytes | final F-RCSD topology 两类正式 fail 的分类、稳定对象 key 与唯一对象计数 helper | 保持纯分类/汇总职责，不承接审计行构建或回退编排 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_topology_connectivity_attachment.py` | `13337` bytes | 新拆出的 attachment、retained identity、node-map 与 relation scope 支撑 | 保持 attachment 与映射职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_topology_connectivity_support.py` | `22403` bytes | 新拆出的 road/node index、coverage cache 与几何/ID primitive | 保持索引、缓存与低层 primitive 职责，不承接审计行编排 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_surface_topology_audit.py` | `88779 -> 12239` bytes | 保留 surface-topology postprocess 正式入口与统计回填；兼容原私有 helper 导入面 | 保持 postprocess 编排职责，不回填候选选择、relation 写回或 IO helper |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_surface_topology_rows.py` | `25487` bytes | 新拆出的 surface audit row 主构建逻辑 | 保持审计行组装职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_surface_topology_selection.py` | `29770` bytes | 新拆出的 surface junction fallback、replacement endpoint 与 midroad projection 选择逻辑 | 保持候选选择和 midroad projection 职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_surface_topology_relation.py` | `19147` bytes | 新拆出的 relation node-map / road-id 写回、topology audit 重建与 summary 合并 | 保持 relation 与审计发布职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_surface_topology_support.py` | `15463` bytes | 新拆出的 surface / Step2 mapping 加载、索引与基础解析 helper | 保持 IO、索引与低层解析职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_advance_right_contract.py` | `101663 -> 39132` bytes | 保留 junction advance-right 与 retained SWSD attachment 两个正式 contract callable，并兼容原私有导入面 | 保持正式契约编排职责，不回填 postprocess 或几何 primitive |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_advance_right_common.py` | `19291` bytes | 新拆出的 contract context、split-point、node mapping 与 audit row 公共逻辑 | 保持公共 contract 支撑职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_advance_right_postprocess.py` | `28462` bytes | 新拆出的 post-advance carrier retention、bridge / paired road 与 midroad attachment 编排 | 保持 postprocess 业务编排职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_advance_right_support.py` | `22564` bytes | 新拆出的 road component、projection、split、snap 与 ID/geometry primitive | 保持低层图/几何支撑职责，不承接 contract 主流程 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_topology_supplement.py` | `65601 -> 56985` bytes | 保留 topology supplement 正式物化、coverage release 与 mixed advance-right 主流程 | 已低于 60KB；后续增长优先继续下沉主流程末端策略 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_topology_supplement_support.py` | `9797` bytes | 新拆出的 supplement road/node/segment 映射、endpoint 与基础几何 helper | 保持低层 supplement 支撑职责 |
| `tests/modules/t06_segment_fusion_precheck/test_step3_segment_replacement.py` | `102076 -> 48367` bytes | 保留 Step3 基础替换、mainnode、junction map 与 attachment 契约回归 | 后续 group / post-advance 场景进入独立测试文件 |
| `tests/modules/t06_segment_fusion_precheck/test_step3_segment_replacement_groups_and_advance.py` | `52823` bytes | 新拆出的 group replacement、special junction 与 post-advance 场景回归 | 达到 55KB 前继续按 group / advance 场景拆分 |
| `tests/modules/t06_segment_fusion_precheck/test_runner_outputs.py` | `93889 -> 44848` bytes | 保留 combined runner 与 Step1/Step2 基础输出、pair gate 回归 | retry / adaptive buffer 场景进入独立测试文件 |
| `tests/modules/t06_segment_fusion_precheck/test_runner_outputs_retry.py` | `47816` bytes | 新拆出的 Step2 retry、adaptive buffer、diagnostic 与 partial roundabout 场景回归 | 保持 retry/output 专项测试职责 |
| `tests/modules/t06_segment_fusion_precheck/test_step3_topology_connectivity_audit.py` | `62155 -> 30469` bytes | 保留 topology connectivity 基础 path、coverage、retained endpoint 与 final road integrity 回归 | 扩展 junction/attachment 场景进入独立测试文件 |
| `tests/modules/t06_segment_fusion_precheck/test_step3_topology_connectivity_audit_extended.py` | `33829` bytes | 新拆出的 segment-road mapping、junction、patch attachment、提右 final topology 与 surface release 回归 | 保持扩展 topology 场景职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/rcsd_unreplaced_attribution.py` | `67670 -> 55763` bytes | 保留 RCSD unreplaced attribution 正式入口、匹配、分类与可 monkeypatch metric callable | 后续 summary 聚合不回填主文件 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/rcsd_unreplaced_attribution_summary.py` | `13411` bytes | 新拆出的 attribution summary、rate、Step3 summary patch 与字段清单 | 保持汇总与发布 schema 职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/text_bundle.py` | `80397 -> 56901` bytes | 保留 T06 text-bundle 正式 API、编码/解码与兼容 CLI callable；调用方式不变 | 已低于 60KB；input slice 与 argparse 实现不回填主文件 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/text_bundle_input.py` | `19559` bytes | 新拆出的 centered input slice、input bundle 构建与分卷输出逻辑 | 保持 input slice 与 bundle 输出职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/text_bundle_cli.py` | `12371` bytes | 新拆出的既有 T06 text-bundle argparse parser 与 from-args 实现 | 不新增或改变入口；保持既有参数和返回码语义 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/buffer_segment_extraction.py` | `98901 -> 21005` bytes | 保留 BufferSegmentExtractor、SpatialFeatureIndex 与原兼容导入面 | 保持 extractor 编排与缓存职责，不回填 graph/supplement/result 实现 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/buffer_segment_models.py` | `3582` bytes | 新拆出的 config/result/context/graph 状态 dataclass 与几何缓存 | 保持内部模型和缓存声明职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/buffer_segment_graph.py` | `35272` bytes | 新拆出的候选图、seed pruning、最短/有向路径与 edge weight 逻辑 | 保持 graph/path 核心职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/buffer_segment_supplement.py` | `28819` bytes | 新拆出的 corridor supplement、visual gap、parallel/semantic bridge 逻辑 | 保持 corridor 扩展与 visual consistency gate 职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/buffer_segment_results.py` | `17699` bytes | 新拆出的 connectivity/coverage 状态、结果物化与 ID/geometry primitive | 保持状态判定和结果组装职责 |
| `tests/modules/t06_segment_fusion_precheck/test_buffer_segment_extraction.py` | `69630 -> 34833` bytes | 保留 buffer extraction 基础、coverage、directed path 与 seed pruning 回归 | corridor supplement 扩展场景进入独立测试文件 |
| `tests/modules/t06_segment_fusion_precheck/test_buffer_segment_extraction_corridors.py` | `34199` bytes | 新拆出的 internal edge、parallel corridor、semantic bridge 与 optional terminal 回归 | 保持 corridor supplement 专项测试职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/replacement_plan.py` | `99579 -> 13360` bytes | 保留 replacement plan / problem registry 两个正式 builder 与兼容私有导入面 | 保持顶层计划编排职责，不回填 row/gate/support 实现 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/replacement_plan_rows.py` | `25617` bytes | 新拆出的 standard、path-corridor group 与 visual repair plan row 构建 | 保持计划行物化职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/replacement_plan_visual_gate.py` | `23024` bytes | 新拆出的 visual road-conflict、prune、connectivity 与 coverage gate | 保持 visual consistency gate 职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/replacement_plan_junction_gate.py` | `32417` bytes | special group、junction alignment、group member gate 与受限后置锚定 gate | 保持 junction/group gate 职责；后置 gate 不下沉到计划行物化层 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/replacement_plan_support.py` | `26319` bytes | risk、pair-anchor、visual release、problem registry 与解析支撑 | 保持公共策略/解析支撑职责 |
| `tests/modules/t06_segment_fusion_precheck/test_replacement_plan.py` | `101577 -> 56115` bytes | 保留 standard/group/visual gate 与基础 plan 回归 | surface-aware 与 junction alignment 场景进入独立测试文件 |
| `tests/modules/t06_segment_fusion_precheck/test_replacement_plan_surface_release.py` | `57377` bytes | surface-aware release、后置锚定、正式 final topology rollback、pair attachment 与 junction alignment 回归 | 已接近 60KB；新增大场景前按 postplan/visual release 拆分 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step2_extract_rcsd_segments.py` | `101536 -> 5832` bytes | 已降为 Step2 正式入口兼容 facade，保留原函数签名与导入面 | 禁止回填主循环、outcome 或发布实现 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step2_extract_rcsd_segments_runner.py` | `56860` bytes | 新拆出的 Step2 输入准备、逐 fusion-unit 主循环、retry 与 gate 编排；显式快照外层 `locals()`，兼容 WSL Python 3.10 与 Windows Python 3.13 | 已低于 60KB；后续主循环增长优先提取新的 outcome 分支 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step2_extract_support.py` | `23984` bytes | 新拆出的 unit 解析、方向/连通、junction attach audit 与 reject row helper | 保持解析、诊断和基础 row 支撑职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step2_extract_outcomes.py` | `18265` bytes | 新拆出的成功、auto pair-anchor 成功与最终拒绝结果物化分支 | 保持 outcome 行写入顺序与原分支语义 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step2_extract_finalize.py` | `23053` bytes | 新拆出的 group/special gate 后处理、工件发布、summary 与 T06Step2Artifacts 组装 | 保持 Step2 发布与可追溯汇总职责 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_detached_carriers.py` | `1147` bytes | 新拆出的 detached junc SWSD carrier helper，负责识别触达 detached junc 的原 SWSDRoad，并从正式 removed SWSDRoad 集合中剥离 | 保持只承接 detached carrier 识别与 unit 字段更新，不承接 Step3 输出编排或拓扑审计 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/attach_promotion.py` | `5062` bytes | 新拆出的孤立挂接 RCSDRoad promotion 后处理 helper，负责全局唯一 lost attach road 的提升与冲突标注 | 保持只承接 attach promotion row 后处理，不承接 buffer extraction 或 graph retry |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/rejected_context.py` | `1377` bytes | 新拆出的 rejected SWSD context 标注 helper，负责为 rejected rows 补齐 SWSD sgrade 与 directionality 上下文 | 保持只承接 rejected row 上下文补齐，不承接拒绝原因判定 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/pair_anchor_auto_retry.py` | `5462` bytes | 新拆出的高置信 pair-anchor 自动重试安全门槛与 effective relation helper；承接缺失 pair anchor 侧保持补全、低分但硬审计通过的缺端补全准入，以及两端原始 pair 已完整时高置信 `candidate_anchor_mismatch` 的候选 relation 准入 | 保持只承接 pair-anchor 自动重试准入，不承接 buffer extraction 主流程 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/pair_anchor_formal_retry.py` | `20450` bytes | formal orientation retry helper，负责单候选 pair anchor mismatch 与单向 `multi_anchor_ambiguous` 的 as-is / reversed 正式试算、正式 buffer extractor、single graph-first 复核与 multi-anchor 端点侧位一致性审计 | 保持只承接 formal retry 判定与 outcome，不承接 Step2 输出行编排 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/pair_anchor_formal_retry_rows.py` | `6600` bytes | 新拆出的 formal retry accepted outcome 输出行 helper，负责 probe、repair、candidate、replaceable 与 failure-business audit 落表 | 保持只承接已通过 outcome 的输出行组装，不承接候选选择与图搜索 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/pair_anchor_relation_retry.py` | `9464` bytes | 新拆出的 relation mapping / buffer extraction formal retry 编排 helper，负责调用正式试算、junc audit 与输出行 helper，并为 Step2 主流程返回统计增量 | 保持只承接 formal retry 编排，不承接候选打分、基础 relation mapping 或 buffer extractor 实现 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/adaptive_buffer_retry.py` | `4364` bytes | 新拆出的高等级 single / dual 受限重审准入 helper；只判断 sgrade/direction/reason/全图诊断是否允许进入 single graph-first 或 dual adaptive buffer | 保持只承接重审准入，不承接 buffer extraction 执行与输出写入 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/single_graph_connectivity_retry.py` | `20749` bytes | 新拆出的高等级单向 RCSD graph-first 纵向联通 helper，负责全图有向 path、50m core、长度与几何参考门槛，并输出可审计的连通性风险 | 保持只承接 single 纵向联通，不承接 Step2 输出行编排 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/single_direction_semantic_retry.py` | `8081` bytes | 单向 Segment 特殊语义端点 subnode 本地 corridor 释放 helper，负责在初始有向 corridor 不可追溯时保持原方向检查本地无向 corridor，并仅允许短 connector / 提前右转 Road 解释方向缺口 | 保持只承接特殊语义端点本地释放，不承接 Step2 输出编排、普通方向推导或 relation 修正 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/buffer_failure_diagnostics.py` | `13363` bytes | 新拆出的 Step2 buffer 失败归因、失败 metric 与 canonical RCSD id helper | 保持只承接失败诊断与 summary/audit helper，不承接 replaceable 构建主流程 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step2_trunk_utils.py` | `100980 -> 60369` bytes | T10 性能治理中保留 Step2 trunk 模型、候选构建、gate 与测试 monkeypatch 面；kind2-128 / trunk evaluation 编排已下沉 | 已低于 60KB；禁止回填 evaluation 主流程 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step2_trunk_evaluation.py` | `40324` bytes | 新拆出的 kind2-128 local corridor、trunk choice、through-collapsed 与 Step5C mirrored evaluation 编排 | 通过动态代理保持 `_enumerate_simple_paths` 与 T-junction gate 的 monkeypatch 语义 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step2_geometry_utils.py` | `4218` bytes | 新拆出的 Step2 trunk 低层几何 helper，承接 geometry coords、line assembly、距离与采样函数 | 保持只承接通用几何 primitive，不承接 pair validation 编排 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step2_candidate_gates.py` | `2021` bytes | 新拆出的 Step2 trunk 候选 gate helper，当前承接 mixed-kind wedge 判定 | 后续候选级 gate 可继续下沉到此文件，避免 `step2_trunk_utils.py` 膨胀 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step2_internal_turn_gate.py` | `8693` bytes | 新拆出的内部语义路口转向角 gate helper，用于阻断多路口面内明显非直行 continuation 的 Segment trunk 候选 | 保持只承接内部路口转向角、incident road 与审计字段，不承接 T06 替换逻辑 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step2_arbitration.py` | `62713 -> 60457` bytes | 保留 pair conflict、component solver、priority 与正式 arbitration 编排；模型已下沉 | 已低于 60KB；后续 solver 扩展优先继续拆分 exact/greedy 分支 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step2_arbitration_models.py` | `2462` bytes | 新拆出的 arbitration option/conflict/metrics/decision/outcome dataclass | 保持仅定义稳定内部模型，并由原模块兼容导出 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step1_pair_poc.py` | `83941 -> 55040` bytes | 保留 Step1 图构建、策略执行、输出与既有 CLI/API；数据模型和搜索实现已下沉并继续兼容导出 | 已低于 60KB；禁止回填搜索主循环和模型定义 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step1_pair_models.py` | `4550` bytes | 新拆出的 Step1 node/road/rule/search/pair/context/result dataclass | 保持仅定义稳定内部模型，并由原模块兼容导出 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step1_pair_search.py` | `26455` bytes | 新拆出的 Step1 搜索、复杂路口等价、reverse confirm 与 pair materialization 实现 | 动态读取 facade 的搜索审计采样限额，保持测试 monkeypatch 与运行语义 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step2_segment_poc.py` | `82416 -> 53427` bytes | 保留 Step2 正式执行/CLI、component tighten 与既有私有测试导入面；pair validation 主循环已下沉 | 已低于 60KB；禁止回填 validation 主循环 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step2_validation_pipeline.py` | `32818` bytes | 新拆出的 pair candidate validation、progress trace、arbitration option 与 tighten 编排 | 通过 facade 动态代理保持测试 monkeypatch 和运行常量语义 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/skill_v1.py` | `80257 -> 47752` bytes | 保留 Skill v1 数据模型、阶段支撑、finalize、continuation 与既有 CLI/API；七阶段主编排已下沉 | 已低于 60KB；禁止回填主运行管线 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/skill_v1_pipeline.py` | `34781` bytes | 新拆出的 Skill v1 初始化、Step2/refresh/Step4/Step5/oneway/Step6、部分运行与汇总编排 | 通过 facade 动态代理保持阶段函数和 finalize 的 monkeypatch 语义 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step5_staged_residual_graph.py` | `75743 -> 49389` bytes | 保留 Step5A/B/C 输入、barrier audit、phase 执行和既有 API/CLI；刷新与总编排已下沉 | 已低于 60KB；禁止回填 refresh/runner 主流程 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step5_staged_pipeline.py` | `31670` bytes | 新拆出的 Step5 刷新物化、三阶段总编排、合并输出与 summary 发布 | 通过 facade 动态代理保持既有内部调用与业务常量语义 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step5_oneway_segment_completion.py` | `82602 -> 38951` bytes | 保留 one-way phase/graph/trace、输出 helper 与既有 API；fallback、attachment、dead-end 和总编排已下沉 | 已低于 60KB；禁止回填 completion 主流程 |
| `src/rcsd_topo_poc/modules/t01_data_preprocess/step5_oneway_pipeline.py` | `48961` bytes | 新拆出的 residual corridor、side attachment、dead-end leaf、final fallback 与 one-way completion 总编排 | 通过 facade 动态代理保持现有 helper、dataclass 和业务常量语义 |
| `tests/modules/t01_data_preprocess/test_step2_segment_poc.py` | `198693 -> 40707` bytes | 保留 candidate channel、基础 validation 与 progress trace 场景 | 共享 fixture/helper 已下沉，其他测试按 tighten/arbitration/gate 场景拆分 |
| `tests/modules/t01_data_preprocess/step2_segment_test_support.py` | `21367` bytes | 新拆出的 Step2 测试 fixture、synthetic dataset 与 record builder | 仅供测试复用，不新增生产入口 |
| `tests/modules/t01_data_preprocess/test_step2_segment_tighten.py` | `58685` bytes | 新拆出的 compact release、component tighten、runtime/output 场景 | 已低于 60KB；新增 tighten 场景优先继续按主题分文件 |
| `tests/modules/t01_data_preprocess/test_step2_segment_arbitration.py` | `38739` bytes | 新拆出的 exact solver、pair conflict 与 strong-anchor arbitration 场景 | 保持 arbitration 专项测试职责 |
| `tests/modules/t01_data_preprocess/test_step2_segment_gates.py` | `34926` bytes | 新拆出的 T-junction、side-bypass、minimal-loop 与 trunk-choice gate 场景 | 保持 trunk/gate 专项测试职责 |
| `src/rcsd_topo_poc/modules/t10_e2e_orchestration/case_runner.py` | `48996` worktree bytes | 保留 T10 manifest/funnel/visual/feedback helper、业务常量与既有 API/CLI；T12 仅增加显式 opt-in stage order 与参数 | 已低于 60KiB；禁止回填 T12 具体编排 |
| `src/rcsd_topo_poc/modules/t10_e2e_orchestration/contracts.py` | `10330` worktree bytes | T10 workflow chain、T11/T12 audit handoff requirements 与 step contract | T12/T11 产物不作为 T09 业务输入 |
| `src/rcsd_topo_poc/modules/t10_e2e_orchestration/case_runner_pipeline.py` | `60207` worktree bytes | package/feedback iteration、逐 case 与逐 stage dispatcher；仅增加最小 T12 分派 | 低于 60KiB但接近安全线；T12 具体编排不得回填 |
| `src/rcsd_topo_poc/modules/t10_e2e_orchestration/case_runner_t11.py` | `3388` worktree bytes | T10 Case runner 的 T11 输入门禁、正式入口调用、run root 与必要输出审计 adapter | 内部模块，不新增正式入口；T11 保持 audit-only |
| `src/rcsd_topo_poc/modules/t10_e2e_orchestration/case_runner_t12.py` | `5070` worktree bytes | T10 Case runner 的 T12 显式输入门禁、正式入口调用和必要输出审计 adapter | 内部模块；T12 默认关闭且保持 audit-only |
| `scripts/t10_run_e2e_cases.sh` | `6113` worktree bytes | 既有 T10 Case runner wrapper，`STOP_AFTER` 文档增加 `t11` | 不新增入口，调用方式保持兼容 |
| `scripts/t10_run_innernet_full_pipeline.sh` | `64067` worktree bytes | 既有内网全量总控增加显式可选 T12 stage、resume、manifest、summary、Case 边界转发、显式 processing CRS 透传、候选后 reviewed 新 run-root 发布与条件完成门禁 | 低于 100KB 硬阈值但已超过 60KiB 软预警线；默认流程不变，T09 仍直接消费 T06 业务输出；后续增长前拆 stage helper |
| `scripts/t12_run_frcsd_quality_audit.py` | `3899` worktree bytes | T12 原始 1V1 F-RCSD 质量审计正式入口 | 参数化输入；不修改输入或执行修复 |
| `tests/modules/t10_e2e_orchestration/test_t10_contracts.py` | `92001 -> 42931` bytes | 保留 manifest、handoff、package、funnel 与 feedback 基础契约回归 | case-runner iteration/visual/finalize 场景进入独立测试文件 |
| `tests/modules/t10_e2e_orchestration/t10_contract_test_support.py` | `9153` bytes | 新拆出的 T10 契约测试 manifest/vector/feedback fixture helper | 仅供测试复用，不新增正式入口 |
| `tests/modules/t10_e2e_orchestration/test_t10_case_runner_contracts.py` | `39939` worktree bytes | runner blocking、feedback iteration、completion、visual summary 与含 T11 的 finalize 回归 | 保持 case-runner 专项测试职责 |
| `tests/modules/t10_e2e_orchestration/test_t10_t11_workflow.py` | `6851` worktree bytes | T06→T11→T09 stage order、adapter、输入门禁、full input discovery 与 legacy finalize 回归 | 仅测试既有入口编排，不新增执行入口 |
| `src/rcsd_topo_poc/modules/t09_swsd_field_rule_restoration/frcsd_restriction.py` | `99397 -> 39468` bytes | 保留 T09 Step3 schema、输入/summary/helper 与既有 callable 导出；carrier/feature/publish 编排已下沉 | 已低于 60KB；禁止回填 Step3 主编排 |
| `src/rcsd_topo_poc/modules/t09_swsd_field_rule_restoration/frcsd_restriction_pipeline.py` | `54689` bytes | 新拆出的 Arm carrier、v1/v2 stable/candidate feature、condition 与 restriction row 编排 | 保持 scope-aware 投影和 stable/candidate 原子分层职责 |
| `src/rcsd_topo_poc/modules/t09_swsd_field_rule_restoration/frcsd_restriction_runner.py` | `11295` bytes | 新拆出的 T09 F-RCSD restriction 顶层读取、写出、summary 与 artifact 组装 | 通过 facade 动态代理保持既有 callable 与 helper 语义 |
| `src/rcsd_topo_poc/modules/t05_junction_surface_fusion/phase2_runner.py` | `97325 -> 40676` bytes | 保留 Phase2 relation/junctionization helper 与既有 callable 导出；输入组织、decision plan 和总编排已下沉 | 已低于 60KB；禁止回填 Phase2 主流程 |
| `src/rcsd_topo_poc/modules/t05_junction_surface_fusion/phase2_pipeline.py` | `23632` bytes | 新拆出的 T11/T04 supplement、target context 与 decision-plan 编排 | 保持证据归一和 target 级计划职责 |
| `src/rcsd_topo_poc/modules/t05_junction_surface_fusion/phase2_run.py` | `44753` bytes | 新拆出的 Phase2 顶层读取、readonly/group/split、relation 发布、summary 与 artifact 组装 | 通过 facade 动态代理保持 helper 语义与 copy-on-write 边界 |
| `tests/modules/t05_junction_surface_fusion/test_phase2_rcsd_junctionization.py` | `84279 -> 38542` bytes | 保留 existing/manual/T10 supplement/T07 与基础 T04 relation 回归 | split/roundabout/cardinality 场景进入扩展测试文件 |
| `tests/modules/t05_junction_surface_fusion/phase2_test_support.py` | `8900` bytes | 新拆出的 Phase2 vector/CSV fixture、evidence field schema 与 runner helper | 仅供测试复用，不新增正式入口 |
| `tests/modules/t05_junction_surface_fusion/test_phase2_rcsd_junctionization_extended.py` | `35147` bytes | 新拆出的 no-related、road split、fallback、roundabout、cardinality 与 canonical grouping 回归 | 保持 Phase2 扩展场景职责 |
| `src/rcsd_topo_poc/modules/p01_arm_build/final_road_next_road.py` | `81045 -> 52338` bytes | 保留 P01-Final role/source policy/matching/review helper 与既有 callable；最终生成循环已下沉 | 已低于 60KB；禁止回填 final generation 主流程 |
| `src/rcsd_topo_poc/modules/p01_arm_build/final_generation.py` | `32099` bytes | 新拆出的 F-RCSD RoadNextRoad 最终规则投影、generation audit 与 result 组装 | 通过 facade 动态代理保持 role/policy/matching helper 语义 |
| `src/rcsd_topo_poc/modules/p01_arm_build/topology.py` | `80217 -> 56664` bytes | 保留 Arm topology primitive、candidate/final Arm 与 review metrics；trace 和 dataset 总编排已下沉 | 已低于 60KB；禁止回填 trace/dataset 主流程 |
| `src/rcsd_topo_poc/modules/p01_arm_build/topology_pipeline.py` | `27604` bytes | 新拆出的 seed trace 与 dataset Arm build 总编排 | 保持 trace 决策、movement/corridor/validation 汇总职责 |
| `tests/modules/p01_arm_build/test_p01_arm_build.py` | `99062 -> 29410` bytes | 保留 final-arm validation、advance-turn 与基础 P01 runner 回归 | final projection/topology/bundle 场景进入独立测试文件 |
| `tests/modules/p01_arm_build/p01_test_support.py` | `16861` bytes | 新拆出的 P01 dataset、validation、movement/source fixture helper | 仅供测试复用，不新增正式入口 |
| `tests/modules/p01_arm_build/test_p01_final_and_bundle.py` | `50849` bytes | 新拆出的 F-RCSD final projection、topology gate、text-bundle 与 IO 回归 | 保持 final/bundle 专项测试职责 |
| `src/rcsd_topo_poc/modules/t11_manual_relation_review/extract.py` | `85083 -> 56222` worktree bytes | 保留 T11 candidate/anchor/relation-gap build、summary 与输出 helper；顶层抽取与输入发现已下沉 | 已低于 60KiB；禁止回填 extract 主编排 |
| `src/rcsd_topo_poc/modules/t11_manual_relation_review/extract_pipeline.py` | `38454` worktree bytes | T10 Case/full pipeline 输入发现、数据读取、基础索引与 T11 candidate 总编排；full layout 使用显式相对路径 | 通过 facade 动态代理保持审计表构建和输出语义 |
| `src/rcsd_topo_poc/modules/t11_manual_relation_review/segment_tables.py` | `29825` worktree bytes | T11 Segment relation 审计表构建；50m RCSD 上下文按节点缓存，并通过空间索引预筛后执行原精确距离判定 | 保持 CRS、`distance <= 50.0`、最近距离、候选排序和几何语义不变 |
| `scripts/t11_extract_relation_repair_candidates.py` | `5445` worktree bytes | 既有 T11 正式入口；保留单用例模式并增加六用例批量受控并行编排 | 不是新增入口；`--workers` 限制 `1..8`，每 Case 输出根隔离 |
| `tests/modules/t11_manual_relation_review/test_extract_cli.py` | `4350` worktree bytes | T11 单用例兼容、批量顺序/输出隔离、worker 边界和人工 CSV 防误用测试 | 仅测试正式入口参数化，不新增执行入口 |
| `tests/modules/t11_manual_relation_review/test_segment_tables_performance.py` | `1159` worktree bytes | T11 50m spatial index 精确阈值、ID 顺序和无命中最近距离回归 | 只覆盖性能实现的业务等价边界 |
| `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/runner.py` | `73529 -> 52064` bytes | 保留 T07 IO、Step1、Step2 helper 与既有 callable；Step2 anchor 主编排已下沉 | 已低于 60KB；禁止回填 Step2 主流程 |
| `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/step2_pipeline.py` | `25418` bytes | 新拆出的 T07 Step2 anchor recognition、error/surface/relation evidence 与 artifacts 编排 | 通过 facade 动态代理保持 fail1/fail2 和 surface handoff 语义 |
| `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/step3_intersection_match.py` | `62695 -> 34883` bytes | 保留 Step3 relation/cardinality/IO/canonical helper 与既有 callable；主匹配编排已下沉 | 已低于 60KB；禁止回填 Step3 主流程 |
| `src/rcsd_topo_poc/modules/t07_semantic_junction_anchor/step3_pipeline.py` | `32478` bytes | 新拆出的 T07 Step3 surface/relation compatibility matching、cardinality 回写与发布编排 | 保持可选补锚定位和 relation evidence 语义 |
| `src/rcsd_topo_poc/modules/t08_preprocess/nodes_type_qc.py` | `78892 -> 46502` bytes | 保留 Tool6 数据模型、解析、拓扑与输出 helper；QC 检测和分类编排已下沉 | 已低于 60KB；禁止回填 Tool6 检测主流程 |
| `src/rcsd_topo_poc/modules/t08_preprocess/nodes_type_qc_pipeline.py` | `36636` bytes | 新拆出的 Tool6 QC 检测、分歧合流与交叉口分类编排 | 通过 facade 动态代理保持 helper、中文错误标签与输出契约语义 |
| `src/rcsd_topo_poc/modules/t08_preprocess/complex_junction_preprocess.py` | `69778 -> 46300` bytes | 保留 Tool5 模型、复杂路口/一对多 helper 与既有 callable 导出；顶层编排已下沉 | 已低于 60KB；禁止回填 Tool5 顶层运行编排 |
| `src/rcsd_topo_poc/modules/t08_preprocess/complex_junction_pipeline.py` | `24470` bytes | 新拆出的 Tool5 输入准备、complex-divmerge、one-to-many 与输出发布编排 | 保持 copy-on-write、CRS、拓扑审计及既有 T02 兼容调用语义 |
| `src/rcsd_topo_poc/modules/t08_preprocess/junction_type_repair.py` | `64985 -> 49670` bytes | 保留 Tool4 模型、解析、拓扑、错误检测和修复 helper；顶层编排已下沉 | 已低于 60KB；禁止回填 Tool4 顶层运行编排 |
| `src/rcsd_topo_poc/modules/t08_preprocess/junction_type_repair_pipeline.py` | `17171` bytes | 新拆出的 Tool4 输入读取、错误检测、契约修复、输出与 summary 编排 | 保持 no-silent-fix、字段语义、CRS 与审计输出不变 |
| `tests/modules/t10_e2e_orchestration/artifact_equivalence.py` | `17013` bytes | T10 性能治理新增的结构化业务等价 helper；比较 CSV/JSON/GPKG 内容，忽略运行元数据和拆分后的物理源码位置，并仅在比较阶段按 `1e-7 m` 规范化浮点噪声；`rcsd_road_ids/frcsd_road_ids` 按明确的无序成员集合比较 | 不作为正式入口；路径序列等其他列表仍顺序敏感，生产几何精度不变，超过网格或业务字段变化仍必须失败 |
| `tests/modules/t10_e2e_orchestration/test_artifact_equivalence.py` | `8530` bytes | 等价 helper 的运行元数据、业务字段、无序 relation road ID 集合、GPKG、浮点噪声和 tree manifest 回归 | 保持覆盖比较器边界，禁止放宽其他正式业务字段 |
| `src/rcsd_topo_poc/modules/t10_e2e_orchestration/scratch_publish.py` | `14231` bytes | T10 既有 wrapper 的临时 Linux 文件系统执行结果发布 helper；负责受校验的 tar 发布、路径回写、清单核验与 scratch 清理 | 不新增正式入口；保持发布前后文件数/字节数一致并限制清理根边界 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_final_topology_gate.py` | `9687` bytes | Final topology 正式失败决策、失败节点证据与 hard-gate plan 回退 helper | 保持决策与 plan 标记职责，不承接 F-RCSD 几何或 relation 编排 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_authoritative_transition_closure.py` | `14812` bytes | hard-gate 直接回退后 mixed-source 级联 transition 的 T05 权威 mainnode 收口与审计 | 保持严格候选、12m 门禁和审计职责，不扩展为通用 surface fallback |

说明：

- 当前未发现 `scripts/` 下超过 `100 KB` 的入口脚本。
- 本表不裁定业务基线、模块正式范围或是否立即重构；只记录结构债事实。
