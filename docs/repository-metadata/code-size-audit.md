# 当前超阈值代码 / 脚本文件审计

## 范围

- 审计日期：2026-05-04
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
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_event_interpretation_core.py` | `57911` bytes | Step4 event interpretation core 仍在 57 KB 档；本轮合并 semantic-boundary 与 arbiter 逻辑后仍低于硬阈值 | 后续保持 case orchestration / candidate pool / evaluation 职责，不回填 unit preparation |
| `tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py` | `58003` bytes | official 39-case baseline 已下沉到 manifest，legacy 23/30 gate 维持轻量 projection；RCSDRoad fallback 裁剪回归更新后仍低于硬阈值 | 后续新增真实 Case 回归优先扩展 manifest 或按场景分文件 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_kernel.py` | `56445` bytes | Step4 runtime kernel 仍承接 final event interpretation 主流程，低于硬阈值但偏大 | 后续若扩展 kernel 主流程，优先拆 multibranch / event-interpretation orchestration |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_rcsd_selection_support.py` | `53171` bytes | RCSD selection support 聚合 semantic group、local/aggregated unit 与 role mapping 支撑逻辑 | 后续扩展 RCSD 选择支撑前先评估 local-unit / aggregated-unit helper 拆分 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly.py` | `49351` bytes | T-01 已拆出 raster/path helper，主 assembly 文件降至 50 KB 以下 | 后续继续保持主流程不回填低层 raster/path helper |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_geometry_base.py` | `48003` bytes | 原 `_runtime_step4_geometry_reference.py` 已改名为 geometry base，低于阈值 | 后续避免重新引入 `reference` 命名误导 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/outputs.py` | `48524` bytes | T04 输出层新增 arbiter ledger / decision trace / review index 字段后接近 50 KB | 后续新增输出字段前优先拆 review-index writer / audit writer helper |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/final_publish.py` | `47805` bytes | Step7 发布层接近 50 KB，但仍低于硬阈值 | 后续新增发布字段前先评估 summary / nodes audit helper 下沉 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_event_interpretation_unit_preparation.py` | `41565` bytes | Round 2 新拆出的 unit preparation / pair-local materialization 模块 | 后续仅承接 preparation 与 scope materialization，不承接 candidate selection |

## 本轮已拆分降险记录

| 原路径 / 新模块 | 体量 | 当前判断 | 建议 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding.py` | `5617` bytes | 已降为 road-surface fork binding facade，保留原 public entrypoint；本轮仅接入 complex SWSD shared RCSDRoad policy | 后续策略扩展优先落到对应 policy 模块，不回填 facade |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_swsd_rcsdroad.py` | `20445` bytes | 新增的 complex SWSD shared RCSDRoad fallback policy，负责无主证据复杂路口整体唯一 RCSDRoad 对齐 | 保持只承接 shared RCSDRoad 消歧与审计更新，不回填 facade |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_promotions.py` | `45299` bytes | 新拆出的 RCSD / junction-window promotion policy 模块，当前为该组最大文件；T-04a dual-write 后仍低于硬阈值 | 后续若继续增长，优先拆 selected-surface partial support 与 junction-window binding |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_cleanup.py` | `20057` bytes | 新拆出的 structure-only retention 与 unbound cleanup policy 模块 | 保持只承接清理 / 保留策略 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_recovery.py` | `16698` bytes | 新拆出的 road-surface recovery policy 模块 | 保持只承接 invalid-divstrip 后的 surface recovery |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_divstrip.py` | `14210` bytes | 新拆出的 divstrip-primary restore policy 模块 | 保持只承接 divstrip 优先级恢复与歧义消解 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/support_domain.py` | `569` bytes | 已降为 Step5 support-domain facade，保留原 public import surface | 后续 Step5 扩展不得回填 facade |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/support_domain_models.py` | `24151` bytes | 新拆出的 Step5 result dataclass 与 vector export，含 negative mask channel 状态输出 | 后续 vector export 如继续增长，可单独下沉 |
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

说明：

- 当前未发现 `scripts/` 下超过 `100 KB` 的入口脚本。
- 本表不裁定业务基线、模块正式范围或是否立即重构；只记录结构债事实。
