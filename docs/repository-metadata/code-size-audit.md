# 当前超阈值代码 / 脚本文件审计

## 范围

- 审计日期：2026-04-23
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
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_event_interpretation_core.py` | `87975` bytes | 距 100 KB 硬阈值不足一轮中型改动，T04 当前最高风险文件 | 后续若继续扩写，应优先拆出 pair-local / candidate materialization / orchestration 子模块 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_types_io.py` | `76769` bytes | 类型与 IO 聚合文件偏大，仍未越过硬阈值 | 后续新增运行时类型前先评估拆分 |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_kernel_reference.py` | `65297` bytes | 当前被 `_runtime_step4_kernel.py` import，不能按无 importer 死代码删除；命名与体量容易误判为归档残留 | 后续结构轮次应明确改名或拆分；本轮仅登记为 active runtime reference debt |
| `src/rcsd_topo_poc/modules/t04_divmerge_virtual_polygon/_runtime_step4_geometry_core.py` | `64063` bytes | Step4 几何常量与核心工具聚合偏大 | 后续几何阈值或 CRS gate 改动前先评估局部拆分 |

说明：

- 当前未发现 `scripts/` 下超过 `100 KB` 的入口脚本。
- 本表不裁定业务基线、模块正式范围或是否立即重构；只记录结构债事实。
