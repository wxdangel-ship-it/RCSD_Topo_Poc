# 当前超阈值代码 / 脚本文件审计

## 范围

- 审计日期：2026-06-12
- 阈值：单文件超过 `100 KB`
- 口径：按 `code-boundaries-and-entrypoints.md`，审计纳入版本管理的 `src/`、`scripts/`、`tests/`、`tools/` 下源码 / 脚本文件。
- 本表只记录结构债事实，不代表本轮进入对应模块正文治理。

## 结果

| 路径 | 体量 | 当前判断 | 建议 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py` | `1030609` bytes | 远超阈值，已构成显著结构债 | 本轮仅刷新审计；后续若继续触碰，需附拆分计划或豁免说明 |
| `tests/modules/t02_junction_anchor/test_virtual_intersection_poc.py` | `262747` bytes | 测试文件超阈值 | 后续若继续扩写，需附拆分计划、夹具下沉或按阶段拆分说明 |
| `tests/modules/t01_data_preprocess/test_step2_segment_poc.py` | `193797` bytes | 测试文件超阈值 | 后续若继续扩写，需附拆分计划、夹具下沉或按阶段拆分说明 |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_step4_event_interpretation.py` | `121438` bytes | T02 Stage4 event interpretation 文件超阈值 | 后续若继续触碰，需先拆分 Step4 interpretation / candidate helper / audit 输出职责或附豁免说明 |
| `tests/modules/t02_junction_anchor/test_stage4_divmerge_virtual_polygon.py` | `118378` bytes | T02 Stage4 集成测试超阈值 | 后续若继续扩写，需按场景拆分测试文件或下沉共享 fixture |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_geometry_utils.py` | `107024` bytes | T02 Stage4 geometry helper 超阈值 | 后续若继续触碰，需拆分 geometry primitive / topology helper / vector export 职责 |

## 未超阈值高风险预警

| 路径 | 体量 | 当前判断 | 建议 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_divmerge_virtual_polygon.py` | `82546` bytes | T02 Stage4 脚本当前低于硬阈值但仍偏大，历史审计记录已刷新 | 后续若继续触碰，需附拆分计划或豁免说明 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_event_interpretation_core.py` | `62954` bytes | Step4 event interpretation core 新增 road-surface fork apex 候选与 RCSD endpoint 扩展开关后仍低于硬阈值 | 后续保持 case orchestration / candidate pool / evaluation 职责，不回填 unit preparation |
| `tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py` | `64221` bytes | official 39-case baseline 已下沉到 manifest；新增 760256 road-surface fork RCSD junction 回归后仍低于硬阈值 | 后续新增真实 Case 回归优先扩展 manifest 或按场景分文件 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_kernel.py` | `56445` bytes | Step4 runtime kernel 仍承接 final event interpretation 主流程，低于硬阈值但偏大 | 后续若扩展 kernel 主流程，优先拆 multibranch / event-interpretation orchestration |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_rcsd_selection_support.py` | `53259` bytes | RCSD selection support 聚合 semantic group、local/aggregated unit 与 role mapping 支撑逻辑；RCSD trace 只允许 degree-2 passthrough | 后续扩展 RCSD 选择支撑前先评估 local-unit / aggregated-unit helper 拆分 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly.py` | `49351` bytes | T-01 已拆出 raster/path helper，主 assembly 文件降至 50 KB 以下 | 后续继续保持主流程不回填低层 raster/path helper |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_geometry_base.py` | `48003` bytes | 原 `_runtime_step4_geometry_reference.py` 已改名为 geometry base，低于阈值 | 后续避免重新引入 `reference` 命名误导 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/outputs.py` | `48524` bytes | T04 输出层新增 arbiter ledger / decision trace / review index 字段后接近 50 KB | 后续新增输出字段前优先拆 review-index writer / audit writer helper |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/final_publish.py` | `47805` bytes | Step7 发布层接近 50 KB，但仍低于硬阈值 | 后续新增发布字段前先评估 summary / nodes audit helper 下沉 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_event_interpretation_unit_preparation.py` | `41565` bytes | Round 2 新拆出的 unit preparation / pair-local materialization 模块 | 后续仅承接 preparation 与 scope materialization，不承接 candidate selection |
| `tests/modules/p01_arm_build/test_p01_arm_build.py` | `96794` bytes | P01 主功能集成测试已逼近 100 KB 硬阈值（差 ~3.2 KB）；本轮 (`p01-four-case-closure-and-field-semantics`) 未追加该文件 | 后续任何 P01 新增测试**禁止**追加到本文件；按场景新建独立测试文件，参考 `tests/modules/p01_arm_build/test_p01_kind_audit.py` |
| `tests/modules/t06_segment_fusion_precheck/test_step3_segment_replacement.py` | `96035` bytes | T06 Step3 主测试文件补充 group replacement 成员级 Road 归属回归后已逼近 100 KB 硬阈值 | 后续 Step3 新增测试禁止继续追加到本文件；按 group replacement / topology supplement / advance-right 场景拆分独立测试文件 |
| `src/rcsd_topo_poc/modules/p01_arm_build/topology.py` | `78424` bytes | 本轮新增 `kind_distribution` audit 字段计算后体量 +371 bytes（从 `78053` 增至 `78424`），仍低于硬阈值；spec `p01-four-case-closure-and-field-semantics` C-2=D | 后续 P01 trace / through 主路径若继续扩展，优先拆分 trace helper / arm aggregation / context build 职责 |
| `src/rcsd_topo_poc/modules/p01_arm_build/final_road_next_road.py` | `72780` bytes | P01-Final 主实现接近 75 KB，承载 `SourceArmPassRule` / ArmSourceProfile / generation decision / source map 多类职责 | 后续若继续扩展 final generation 规则，优先拆出 rule abstraction / projection / source mapping helper |
| `src/rcsd_topo_poc/modules/p01_arm_build/final_arm_validation.py` | `53011` bytes | FinalArm relaxed reverse / supplemental trace validation 实现 | 后续若继续扩展 validation 分支，优先拆 validation builder 与 evidence helper |
| `src/rcsd_topo_poc/modules/p01_arm_build/review.py` | `52972` bytes | P01 retained audit PNG / review GPKG 图层 helper | 后续 review 输出扩展先评估 layer builder / png renderer 拆分 |

## 本轮已拆分降险记录

| 原路径 / 新模块 | 体量 | 当前判断 | 建议 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding.py` | `5617` bytes | 已降为 road-surface fork binding facade，保留原 public entrypoint；本轮仅接入 complex SWSD shared RCSDRoad policy | 后续策略扩展优先落到对应 policy 模块，不回填 facade |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_swsd_rcsdroad.py` | `20445` bytes | 新增的 complex SWSD shared RCSDRoad fallback policy，负责无主证据复杂路口整体唯一 RCSDRoad 对齐 | 保持只承接 shared RCSDRoad 消歧与审计更新，不回填 facade |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_promotions.py` | `49250` bytes | 新拆出的 RCSD / junction-window promotion policy 模块，当前为该组最大文件；补齐唯一 positive RCSD 发布归一化后仍低于硬阈值 | 后续若继续增长，优先拆 selected-surface partial support 与 junction-window binding |
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
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step2_extract_rcsd_segments.py` | `99324` bytes | 继续授权拆分后保留 Step2 主流程、上下文准备、helper 调用、统计累加与输出编排；special junction group gate、RCSD semantic/internal road coverage、graph edge 准备、group replacement audit 与特殊语义端点本地 corridor 释放已下沉 | 后续 Step2 自动兜底、失败归因与 group replacement 扩展不得回填主文件，必须优先下沉到专用 helper；本文件已极接近 100 KB，后续新增逻辑必须先拆分 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/replacement_plan.py` | `84931` bytes | Step2 replacement plan 生成与 visual consistency / road conflict gate 编排，path-corridor group 风险只进入审计标记，不阻断 standard Segment fallback | 后续 plan gate 扩展优先下沉到专用 helper，避免主计划文件继续膨胀 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step2_special_junctions.py` | `11229` bytes | 新拆出的 Step2 special junction group gate、RCSD semantic/internal road coverage 与 graph edge helper | 保持只承接特殊路口组门控、RCSD graph/coverage 准备与审计，不承接 buffer extraction 主流程 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/group_replacement_audit.py` | `24264` bytes | Step2 group replacement 审计 helper，识别 rejected Segment 的 RCSD 图路径是否跨越外部 accepted SWSD anchor，输出 incident closure / path corridor 闭包状态，并对 path-corridor group union 执行正式 extractor probe | 保持只承接 group closure 与正式 probe 审计，不直接改写 replaceable |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_group_replacement.py` | `18045` bytes | Step3 path-corridor group replacement 消费 helper，新增成员级 Road 归属过滤与 standard ready 成员优先保护，避免 group union 直接污染成员 Segment relation | 保持只承接 group audit / replacement plan 到 Step3 assignment 的解析、分组与成员级作用域过滤，不承接 Road/Node 删除和 F-RCSD 输出 |
| `src/rcsd_topo_poc/modules/t06_segment_fusion_precheck/step3_segment_replacement.py` | `98248` bytes | Step3 主流程仍逼近 100 KB；group replacement apply 逻辑已下沉到 helper，主文件保留编排调用 | 后续 Step3 新增替换策略、拓扑审计或 carrier 处理禁止回填主文件，必须继续下沉到专用 helper |
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

说明：

- 当前未发现 `scripts/` 下超过 `100 KB` 的入口脚本。
- 本表不裁定业务基线、模块正式范围或是否立即重构；只记录结构债事实。
