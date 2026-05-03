# 当前超阈值代码 / 脚本文件审计

## 范围

- 审计日期：2026-05-03
- 阈值：单文件超过 `100 KB`
- 口径：按 `code-boundaries-and-entrypoints.md`，审计纳入版本管理的 `src/`、`scripts/`、`tests/`、`tools/` 下源码 / 脚本文件。
- 本表只记录结构债事实，不代表本轮进入对应模块正文治理。

## 结果

| 路径 | 体量 | 当前判断 | 建议 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/t02_junction_anchor/virtual_intersection_poc.py` | `990136` bytes | 远超阈值，已构成显著结构债 | 本轮仅刷新审计；后续若继续触碰，需附拆分计划或豁免说明 |
| `src/rcsd_topo_poc/modules/t02_junction_anchor/stage4_divmerge_virtual_polygon.py` | `353513` bytes | 远超阈值，已构成显著结构债 | 本轮仅刷新审计；后续若继续触碰，需附拆分计划或豁免说明 |
| `tests/modules/t02_junction_anchor/test_virtual_intersection_poc.py` | `252529` bytes | 测试文件超阈值 | 后续若继续扩写，需附拆分计划、夹具下沉或按阶段拆分说明 |
| `tests/modules/t01_data_preprocess/test_step2_segment_poc.py` | `193797` bytes | 测试文件超阈值 | 后续若继续扩写，需附拆分计划、夹具下沉或按阶段拆分说明 |

## 未超阈值高风险预警

| 路径 | 体量 | 当前判断 | 建议 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_types_io.py` | `76769` bytes | 类型与 IO 聚合文件偏大，仍未越过硬阈值 | 后续新增运行时类型前先评估拆分 |
| `tests/modules/t04_divmerge_virtual_polygon/test_step7_final_publish.py` | `83274` bytes | T04 Step7 / Anchor_2 baseline 测试聚合偏大，本轮补入 barrier-separated negative mask、SWSD-window RCSDRoad fallback、`765050` shared RCSDRoad baseline、39 Case official gate 与硬负向掩膜拒绝口径后仍低于硬阈值 | 后续新增真实 Case 回归时优先拆分按场景分组的测试文件 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly.py` | `81561` bytes | Step6 raster assembly 仍聚合偏大；2026-05-03 已拆出 result dataclass、guard context 与部分 relief helpers，并补入分通道 negative mask / bridge crossing / ambiguous alignment gate / relief constraint audit / accepted 单联通强门禁；本轮补入 SWSD section-window 合并边界与受审计 relief 后置约束 | 后续继续拆出 raster/path assembly helpers |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_kernel_base.py` | `65292` bytes | 原 `_runtime_step4_kernel_reference.py` 已改名为 active kernel base，体量仍偏大但低于阈值 | 后续 kernel base 语义扩展前评估局部拆分 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_geometry_core.py` | `64063` bytes | Step4 几何常量与核心工具聚合偏大 | 后续几何阈值或 CRS gate 改动前先评估局部拆分 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_rcsd_anchored_reverse.py` | `59920` bytes | RCSD reverse lookup、terminal continuation、post-conflict recheck 和 audit 更新聚合偏大 | 后续继续扩展 reverse policy 前先拆 policy / graph helpers |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_event_interpretation_core.py` | `55532` bytes | Round 2 已拆出 `_event_interpretation_unit_preparation.py`，主文件从 94 KB 降至 55 KB | 后续保持 case orchestration / candidate pool / evaluation 职责，不再把 unit preparation 回填进主文件 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_geometry_base.py` | `48003` bytes | 原 `_runtime_step4_geometry_reference.py` 已改名为 geometry base，低于阈值 | 后续避免重新引入 `reference` 命名误导 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_event_interpretation_unit_preparation.py` | `41565` bytes | Round 2 新拆出的 unit preparation / pair-local materialization 模块 | 后续仅承接 preparation 与 scope materialization，不承接 candidate selection |

## 本轮已拆分降险记录

| 原路径 / 新模块 | 体量 | 当前判断 | 建议 |
|---|---:|---|---|
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding.py` | `5334` bytes | 已降为 road-surface fork binding facade，保留原 public entrypoint；本轮仅接入 complex SWSD shared RCSDRoad policy | 后续策略扩展优先落到对应 policy 模块，不回填 facade |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_swsd_rcsdroad.py` | `13727` bytes | 新增的 complex SWSD shared RCSDRoad fallback policy，负责无主证据复杂路口整体唯一 RCSDRoad 对齐 | 保持只承接 shared RCSDRoad 消歧与审计更新，不回填 facade |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_promotions.py` | `34638` bytes | 新拆出的 RCSD / junction-window promotion policy 模块，当前为该组最大文件 | 后续若继续增长，优先拆 selected-surface partial support 与 junction-window binding |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_cleanup.py` | `17584` bytes | 新拆出的 structure-only retention 与 unbound cleanup policy 模块 | 保持只承接清理 / 保留策略 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_recovery.py` | `16698` bytes | 新拆出的 road-surface recovery policy 模块 | 保持只承接 invalid-divstrip 后的 surface recovery |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/step4_road_surface_fork_binding_divstrip.py` | `14210` bytes | 新拆出的 divstrip-primary restore policy 模块 | 保持只承接 divstrip 优先级恢复与歧义消解 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/support_domain.py` | `569` bytes | 已降为 Step5 support-domain facade，保留原 public import surface | 后续 Step5 扩展不得回填 facade |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/support_domain_builder.py` | `42901` bytes | 新拆出的 Step5 unit/case domain builder orchestration，已承接 SWSD/RCSD negative mask 分通道、no-RCSD 相关道路归属逻辑与 complex shared RCSDRoad 下的 SWSD 关系补全；本轮移除正向走廊 / allowed growth 对 unrelated 掩膜的几何削弱 | 后续优先进一步拆 precompute / case-level bridge assembly |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/support_domain_models.py` | `24151` bytes | 新拆出的 Step5 result dataclass 与 vector export，含 negative mask channel 状态输出 | 后续 vector export 如继续增长，可单独下沉 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/support_domain_common.py` | `19458` bytes | 新拆出的 Step5 geometry / axis / scenario common helper | 保持无 case orchestration 职责 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly_models.py` | `12704` bytes | 新拆出的 Step6 result dataclass 与状态 / 审计序列化模型，含 bridge negative mask、case alignment review、relief constraint audit 与 barrier-separated 字段 | 保持只承接 Step6 结果模型，不回填 assembly 算法 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly_guards.py` | `4044` bytes | 新拆出的 Step6 guard context 与场景派生逻辑 | 保持只承接 Step6 guard 上下文，不回填 raster assembly 或 relief 算法 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/polygon_assembly_relief.py` | `5663` bytes | 新拆出的 Step6 dominant component / cut-sliver / hole relief helper | 保持只承接不依赖 raster 主流程状态的 relief helper |

说明：

- 当前未发现 `scripts/` 下超过 `100 KB` 的入口脚本。
- 本表不裁定业务基线、模块正式范围或是否立即重构；只记录结构债事实。
