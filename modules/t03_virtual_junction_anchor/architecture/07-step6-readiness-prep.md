# 07 Step6 Readiness Prep

## 目标

- 为后续 `Step6` 做轻量整备，不做大规模重构，不引入 `Step6` 正式业务逻辑。

## 当前识别出的候选抽离点

### 1. shared geometry primitives

- 候选来源：
  - `step45_rcsd_association.py`
  - `step45_foreign_filter.py`
  - `step45_render.py`
- 候选内容：
  - `allowed-space / current-surface / selected-corridor` 的公共几何裁剪
  - line / point / polygon 的 `_clean / _union / _extract` 小工具
  - support fragment 与 hook zone 的基础几何操作
- 当前决策：
  - 先不抽文件
  - 维持在 `Step45` 层内，等 `Step6` 真正落地后再按复用证据抽离

### 2. status-audit adapter

- 候选来源：
  - `step45_rcsd_association.py`
  - `step45_writer.py`
- 候选内容：
  - `Step45CaseResult -> step45_status.json`
  - `Step45CaseResult -> step45_audit.json`
  - gate failure / normal result 的字段对齐
- 当前决策：
  - 本轮只把字段口径收紧到稳定契约
  - 不单独拆 adapter 模块，避免在 `Step45` closeout 轮引入额外结构漂移

### 3. Step45 classifier boundary

- 当前边界：
  - `step45_loader` 负责 prerequisite 装配与显式校验
  - `step45_rcsd_association` 负责 `A / B / C` 分类与主状态输出
  - `step45_foreign_filter` 负责 excluded / foreign 结果
- `Step6` 进入前建议保持：
  - `association_class` 继续只表达 `A / B / C`
  - `association_blocker` 继续只表达 gate failure / prerequisite blocker
  - `Step6` 不直接回写 `Step45` 的分类枚举

## 本轮明确不做

- 不提前抽共享 geometry utils 文件
- 不提前拆 status/audit adapter
- 不把 `Step6` 的 polygon / acceptance / final decision 逻辑偷渡进来
