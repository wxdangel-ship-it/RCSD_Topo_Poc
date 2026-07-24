# Validation Summary: P05 M0

## 1. 验收对象

- 最终候选 run：`outputs/_work/p05_neural_road_generation/p05_m0_20260721_06`
- Case 根：`E:\TestData\POC_Data`
- baseline 优先级：六案 `t10_six_4b1c496_20260715_070100`，随后 52 案 `t10_full_96b0ea5_20260710_060735`
- split seed：`p05-m0-v1`
- `silent_fix=false`

## 2. 真实数据结果

| 指标 | 结果 | 判定 |
|---|---:|---|
| 归档样本 | `741` | PASS |
| 稳定业务组 | `726` | PASS |
| T03/T04 单点样本 | `689` | PASS |
| T10 Case/Segment 样本 | `52` | PASS |
| label artifacts | `520`，每个 T10 Case 各 `10` 个 role | PASS |
| T10 RoadGraph 可训练 | `51/52 = 98.08%` | PASS，超过 `95%` |
| 用户确认排除 | `1` | PASS，不进入训练/Oracle |
| 待复评 quarantine | `0` | PASS |
| 任一任务可训练 | `740/741 = 99.87%` | PASS；排除样本全部 task mask 关闭 |
| group 跨 split 泄漏 | `0` | PASS |
| 重复运行 split hash | `_05 == _06` | PASS |
| 可用 truth Oracle | `51/51` | PASS |
| 定向破坏检测 | `5/5` | PASS |
| 输出 hash 校验 | `0` mismatch | PASS |
| 实际 wall time | `14.697s` | 记录完成 |
| 峰值 RSS | `225964032 bytes`，约 `215.5 MiB` | 记录完成 |
| GPU | 未使用 | 符合 M0 边界 |

fold 分布：fold0 `152`、fold1 `128`、fold2 `155`、fold3 `155`、fold4 `151`；固定视图为 test `152`、validation `128`、train `461`。

## 3. 标签权重结果

| scope | 数量 | target/context |
|---|---:|---|
| T03/T04 单点 | `689` | `1.0 / 0.3` |
| T10 Case | `6` | `0.7 / 0.7` |
| T10 Segment | `46` | `0.7 / 0.3` |

## 4. 异常与隔离

- `15` 个 `multiple_archived_versions` warning：同一 junction/Segment 的不同归档 checksum 共享业务 group，已阻止跨 fold 泄漏。
- `1` 个 `organization_manifest_fallback` warning：T10 Case `1885118` 缺目录级 evidence manifest，使用顶层显式 organization record；未用目录猜测替代。
- `1` 个 `approved_sample_exclusion` info：`T10-Error / 1213556_1263661` 的 T06 Road `49689175` 引用不存在的 `snodeid=5395163145640128`。用户于 2026-07-21 确认先排除并继续推进；该样本保留 artifact lineage、split assignment 和 integrity evidence，`object_scene=false / road_graph=false`，未删除或修复 baseline，不再计入待复评 quarantine。

## 5. FR 核对

- FR-001~FR-006：独立 P05、T06 目标语义、限定根及 `1.0/0.7/0.3` 已由模块 source-of-truth、inventory 和真实 CSV 验证。
- FR-007~FR-012：manifest/hash、显式 baseline、passed/integrity gate、业务 group、五折和异常审计已验证。
- FR-013~FR-016：identity-first evaluator、确定性 geometry fallback、CRS/拓扑/几何/审计/性能和不可变 run root 已验证。
- FR-017~FR-019：T01-T06 只读；无新增训练依赖和正式入口；12 个源码/测试文件均低于 100KB，并同步 code-size audit。
- FR-020~FR-022（含 FR-021A）：八类 M0 正式产物、no-silent-fix 异常清单、参数化用户排除、项目/模块源事实和生命周期同步完成。

结论：FR-001~FR-022 全部 PASS。

## 6. SC 核对

- SC-001~SC-003：七个 Case 家族共 `741` 样本全部清点，Segment ID 解析 `46/46`。
- SC-004~SC-005：group 泄漏 `0`，重复运行 split 完全一致。
- SC-006：未修改输入、baseline 或原始几何，manifest 明确 `silent_fix=false`。
- SC-007：T10 RoadGraph 可训练率 `98.08%`，任一任务可训练率 `99.87%`。
- SC-008：通过 integrity gate 且未被用户排除的 Oracle `51/51`，全部精确自比较；用户确认排除 `1`，待复评 quarantine `0`。
- SC-009：缺 Road、方向错误、source 错误、端点移动和拓扑断裂检出 `5/5`。
- SC-010：manifest/CSV/JSON 记录输入与 artifact hash、参数、环境、输出 hash、耗时、对象量、峰值 RSS 和 `silent_fix=false`。

结论：SC-001~SC-010 全部 PASS。

## 7. 自动化验证

- `python -m compileall -q src/rcsd_topo_poc/modules/p05_neural_road_generation tests/modules/p05_neural_road_generation`
- `python -m pytest tests/modules/p05_neural_road_generation -q` → `10 passed`
- P05 + `field_names` + T00 common IO 联合最小回归 → `19 passed, 1 failed`；唯一失败来自本轮未触碰的既有 `t12_frcsd_quality_audit/carrier_graph.py` `.lower()` 扫描，`git diff` 确认 P05 未修改该文件，未越界修复 T12。
- 当前机器无 Python 3.10 解释器，真实运行使用 Python `3.12.9`；12 个新增源码/测试文件另经 `ast.parse(feature_version=(3, 10))` 全部通过 Python 3.10 语法校验。GIS 依赖为 Fiona `1.10.1`、Shapely `2.1.2`、pyproj `3.6.1`，均落在 `pyproject.toml` 声明范围内。
- 真实 run output hash mismatch：`0`
- 源码/测试最大文件：`16749 bytes`
- 未修改 `pyproject.toml`、`src/rcsd_topo_poc/cli.py`、`scripts/`、`docs/repository-metadata/entrypoint-registry.md`
