# Plan: T04 Step4 正向 RCSD 选择器重构

## 最小重构路径

### 1. 文档与契约

- 更新线程 `REQUIREMENT.md`
- 更新 T04 `INTERFACE_CONTRACT.md`
- 更新 `architecture/04-solution-strategy.md`
- 视需要补 `10-quality-requirements.md`

### 2. 正式选择器落在 T04

- 新增 `rcsd_selection.py`
- 正式输出全部由 T04 selector 产出：
  - `selected_rcsdroad_ids`
  - `selected_rcsdnode_ids`
  - `primary_main_rc_node`
  - `positive_rcsd_support_level`
  - `positive_rcsd_consistency_level`
  - `required_rcsd_node`
- 旧 T02 bridge 仅保留：
  - 事件几何
  - legacy debug / raw bridge 信息

### 3. T04 orchestrator 接线

- `event_interpretation.py`
  - 去掉 pair-local RCSD 空时回退到 scoped/case 世界
  - 在主证据和事实点确定后调用新 selector
  - 正式结果字段不再从 `legacy_step5_bridge` 取值

### 4. 输出与审计

- `case_models.py`
  - 增加正式 RCSD audit 字段
- `outputs.py`
  - 透传新字段到 JSON / CSV / GPKG
- `review_render.py`
  - 表达 pair-local 讨论范围、first-hit、local RCSD unit、required node、A/B/C 原因

### 5. 测试与回归

- 保留现有 Step4 baseline 守门
- 新增：
  - pair-local RCSD 为空 => `C / no_support`
  - `required_rcsd_node` 不依赖 `A`
  - 正式结果跟 pair-local selector 一致，不被 legacy bridge 覆盖

## 风险

- 切断回退后，部分 case 会从旧 `B` / 假支持变成 `C / no_support`
- `required_rcsd_node` 放开后，历史输出会变化
- review / index / summary schema 增量字段可能影响已有消费

## baseline 保护点

- Step1-3 不回退
- Step4 主证据 baseline 不回退
- `step4_review_index.csv` / `step4_review_summary.json` / `step4_event_evidence.gpkg` 保持可消费
- `Anchor_2` 冻结 case 至少核对：
  - `17943587`
  - `857993`
  - `30434673`
  - `785675`

