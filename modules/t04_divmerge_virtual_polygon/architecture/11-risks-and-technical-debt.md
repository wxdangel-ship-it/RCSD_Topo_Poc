# 11 Risks And Technical Debt

## 当前冻结前提

- 当前业务基线为 Anchor_2 full baseline：`23 case / accepted = 20 / rejected = 3`。
- `857993 = rejected` 是人工验收确认后的正确业务结果，不作为待修成 `accepted` 的缺陷。
- 最终发布状态机只允许 `accepted / rejected`，不得重新引入最终 `review / review_required`。
- 本文件只登记治理风险与技术债，不改变 Step1-7 业务语义。

## Source-of-truth 风险

- `INTERFACE_CONTRACT.md` 是模块接口与稳定字段的主契约。
- `architecture/04-solution-strategy.md` 只解释架构策略，不平行重述 Step4 细则。
- `architecture/10-quality-requirements.md` 维护质量门槛、回归门槛与 baseline gate。
- 若 acceptance 数字口径冲突，以当前 full baseline `23 / 20 / 3` 为准；`7 / 1` 仅保留为 2026-04-22 selected-case legacy 口径。

## 已知技术债

| 风险项 | 当前事实 | 影响 | 后续处理 |
|---|---|---|---|
| 大文件逼近硬阈值 | `_event_interpretation_core.py` 已拆出 `_event_interpretation_unit_preparation.py`，`step4_road_surface_fork_binding.py` 已拆出 geometry / RCSD helper | 后续中型追加风险降低，但 `_runtime_types_io.py / support_domain.py` 仍偏大 | Round 2 已做最小拆分并同步 `code-size-audit.md`；后续继续按体量规则守门 |
| runtime 命名误导 | `_runtime_step4_kernel_base.py / _runtime_step4_geometry_base.py` 当前为 active base | reference/base 误导已降低，仍需避免后续再新增 `reference` 语义入口 | Round 2 已完成 reference -> base 收口 |
| batch 异常可观测性不足 | `batch_runner` 已写 failure doc、traceback 与 summary failure reason | 失败 case 已可追踪；full-input 侧可在 Round 3 再统一审计口径 | Round 2 已补 failure doc |
| `run_root` 删除风险 | `run_root` 删除前已有 protected-directory 与 immediate-child guard | 误配置风险下降 | Round 2 已增加 guard |
| artifact 版本追踪不足 | batch / case 关键 JSON 已补 `produced_at / git_sha / input_dataset_id` | GPKG feature 层仍可在 Round 3 继续补强 | Round 2 已补最小追溯字段 |
| 视觉黄金图守门不足 | 当前有人工 review PNG，但未形成最小 golden gate | 难以自动发现视觉漂移 | Round 3 设计并尽量落地 |

## GIS 与拓扑风险

- CRS 当前以 EPSG:3857 为前提；后续实现改动必须确认输入 CRS 与坐标变换路径，不得依赖隐式假设。
- `buffer(0)`、`buffer(1e-6)` 等几何清理只能用于数值误差吸收，不得 silent fix 真正拓扑错误。
- Step5 / Step6 的 `allowed_growth_domain / forbidden_domain / terminal_cut_constraints` 是硬边界；任何 polygon cleanup 后都必须重新套用。
- 审计材料必须能定位输入、参数、输出和运行环境；当前版本追踪不足已列入 Round 2 / Round 3。

## 不作为本轮风险展开的事项

- 不推进 T03/T04 成果统一命名。
- 不新增 repo 官方 CLI。
- 不重开 Step4-7 业务语义。
- 不把 `STEP4_REVIEW` 常态解释为最终失败。
