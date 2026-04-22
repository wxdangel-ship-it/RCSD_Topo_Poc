# Plan: T04 Step4 正向 RCSD 选择器正式重构（aggregated / polarity / presence）

## 最小改造路径

### 1. 文档

- 更新线程 `REQUIREMENT.md`
- 更新 `INTERFACE_CONTRACT.md`
- 更新 `04-solution-strategy.md`
- 更新 `10-quality-requirements.md`

### 2. selector

- 保留现有几何 / first-hit / trace 工具
- 将 `resolve_positive_rcsd_selection()` 拆成：
  - raw observation
  - local unit
  - aggregated unit
  - polarity normalization
  - presence/support
  - required node

### 3. 输出

- 在 `case_models.py` / `outputs.py` / `review_audit.py` / `review_render.py` 中增加：
  - `positive_rcsd_present`
  - `aggregated_rcsd_unit_id`
  - `aggregated_rcsd_unit_ids`
  - `axis_polarity_inverted`
  - `required_rcsd_node_source`

### 4. 测试

- 保留 pair-local empty 守门
- 新增：
  - `positive_rcsd_present`
  - side-label mismatch 不再单独压成 `C`
  - `aggregated` 可将多个 partial local units 升级

## 风险

- 旧样本会从 `C` 上浮到 `B`
- `required_rcsd_node` 输出会增加
- 仍有独立 real-case 拓扑守门问题未闭环

## baseline 保护

- `primary_candidate_id / layer / selected_evidence_state / review_state` 不回退
- `selected_candidate_region` 继续只作容器
- review / index / summary 保持可消费
