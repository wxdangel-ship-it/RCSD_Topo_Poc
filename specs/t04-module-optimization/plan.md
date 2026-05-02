# T04 Module Optimization Plan

## 1. Strategy

优化按“审计 -> 低风险机械拆分 -> 测试补强 -> 后续结构拆分”的顺序推进。

当前轮次执行一个可回退的低风险切片：从 `support_domain.py` 拆出 Step5 surface window config 和常量，保持原 public import 面不变。

## 2. Role Responsibilities

| Role | Responsibility | Output |
|---|---|---|
| Product | 校验需求合理性、人工审计结论与测试断言是否一致 | 需求缺口与基线清单 |
| Architecture | 拆分边界、入口边界、体量治理 | 拆分顺序与文档同步清单 |
| Development | 执行低风险机械拆分，避免行为漂移 | 小步代码变更 |
| Testing | 选择防漂移测试组合，识别缺口 | 当前门禁与后续测试任务 |
| QA | CRS、拓扑、几何语义、审计、性能与发布一致性 | 验收 checklist |

## 3. Implementation Slices

### Slice 1 - Step5 scenario/config extraction

- 新增 `support_domain_scenario.py`。
- 从 `support_domain.py` 移出 Step5 window constants、`Step5SurfaceWindowConfig`、`derive_step5_surface_window_config`。
- `support_domain.py` 保留 re-export，避免调用方改动。
- 更新 `architecture/05-building-block-view.md` 和 `code-size-audit.md`。
- 修正 T04 发布与 case-level GPKG 写盘，显式写入 `EPSG:3857` CRS metadata。

### Slice 2 - Step4 road-surface fork binding split

- 后续拆出 SWSD/RCSD window conversion、structure-only retention、binding promotion policy。
- 保持 `apply_road_surface_fork_binding(...)` 作为 facade。
- 拆分前先补 action-level semantic tests。

### Slice 3 - Step5 models / terminal / fill / bridge split

- 后续继续从 `support_domain.py` 拆出 result models、terminal cut、junction fill、bridge helpers。
- 每个切片只做 move-only 或局部 helper extraction。

### Slice 4 - Step6 assembly split

- 拆出 guard context、relief helpers、result dataclass。
- 先补 `component_count / hole_count / post_cleanup_*` 回归。

### Slice 5 - Baseline strengthening

- 增加统一 39-case baseline gate。
- 将新增 6 case 的所有 event unit 关键语义字段纳入断言。
- 逐步拆分过重的 `test_step7_final_publish.py` 测试常量和 fixture。

## 4. Verification Matrix

- Syntax: `py_compile` for modified Python files.
- Unit: Step5 support domain, Step6 assembly, Step4 scenario classification.
- Real baseline: Anchor_2 new 6 gate and original 30 gate.
- QA: 39 case rerun, GPKG valid geometry, summary/audit/nodes consistency.

## 5. Risks

- `step4_road_surface_fork_binding.py` 仍接近 100 KB，后续不能继续追加功能。
- `support_domain.py` 虽已降低到 95 KB 左右，仍接近阈值。
- 39-case gate 当前不是正式测试函数，需要后续落地。
- 当前 worktree 已包含上一轮业务修复；本轮优化以当前 worktree 为基线验证，不回退既有改动。
