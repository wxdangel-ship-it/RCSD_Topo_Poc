# 07 Step6 Readiness Prep

> 本文件保留为 Finalization 正式落地前的历史准备记录。当前正式 Finalization 契约与 closeout 已由 `INTERFACE_CONTRACT.md` 与 `history/step6-step7-finalization-closeout.md` 接管；本文件不再定义当前正式范围。

## 目标

- 为后续 `Step6` 做轻量整备，不做大规模重构，不引入当时尚未正式吸收的 `Step6` 业务逻辑。

## 当前识别出的候选抽离点

### 1. shared geometry primitives

- 候选来源：
  - `step4_association.py`
  - `step5_foreign_filter.py`
  - `association_render.py`
- 候选内容：
  - `allowed-space / current-surface / selected-corridor` 的公共几何裁剪
  - line / point / polygon 的 `_clean / _union / _extract` 小工具
  - support fragment 与 hook zone 的基础几何操作
- 当时决策：
  - 先不抽文件
  - 维持在 `Association` 层内，等 `Step6` 真正落地后再按复用证据抽离

### 2. status-audit adapter

- 候选来源：
  - `step4_association.py`
  - `association_outputs.py`
- 候选内容：
  - `AssociationCaseResult -> association_status.json`
  - `AssociationCaseResult -> association_audit.json`
  - gate failure / normal result 的字段对齐
- 当时决策：
  - 先把字段口径收紧到稳定契约
  - 不单独拆 adapter 模块，避免在 `Association` closeout 轮引入额外结构漂移

### 3. Association classifier boundary

- 历史边界：
  - `association_loader` 负责 prerequisite 装配与显式校验
  - `step4_association` 负责 `A / B / C` 分类与主状态输出
  - `step5_foreign_filter` 负责 excluded / foreign 结果
- 这些边界随后已被 Finalization 正式吸收，但本页保留其历史准备语义

## 本页已被后续正式文档吸收的点

- `association_class` 继续只表达 `A / B / C`
- `association_blocker` 继续只表达 gate failure / prerequisite blocker
- `Step6` 不直接回写 `Association` 的分类枚举

## 本轮明确不做

- 不提前抽共享 geometry utils 文件
- 不提前拆 status/audit adapter
- 不把准备文档误写成当前 Finalization 正式契约
