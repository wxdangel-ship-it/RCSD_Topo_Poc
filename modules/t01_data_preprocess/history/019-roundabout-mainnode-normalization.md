# 019 - 环岛 mainnode 归一化修正

## 背景
- 现有环岛预处理已经会在 working layer 上把环岛 `mainnode` 记为 `grade_2 = 1 / kind_2 = 64`，把 member node 记为 `grade_2 = 0 / kind_2 = 0`。
- 但此前只改 `working_mainnodeid`，不改 `mainnodeid`。
- 在环岛样例中，这会导致：
  - 环岛语义组的 `mainnodeid` 与 `working_mainnodeid` 不一致
  - 下游人工审计时看到环岛组内 node 的原始 `mainnodeid` 仍未归一化

## 本轮 accepted 口径
- 默认仍保持：raw `mainnodeid` 不随一般业务规则改写。
- 例外：环岛预处理允许同步改写环岛组内 node 的：
  - `mainnodeid`
  - `working_mainnodeid`
- 两者统一指向环岛 `mainnode`。

## 结果
- 环岛 `mainnode`
  - `mainnodeid = roundabout mainnode`
  - `working_mainnodeid = roundabout mainnode`
  - `grade_2 = 1`
  - `kind_2 = 64`
- 环岛 member node
  - `mainnodeid = roundabout mainnode`
  - `working_mainnodeid = roundabout mainnode`
  - `grade_2 = 0`
  - `kind_2 = 0`

## 影响范围
- 改动点仅在 `working_layers.roundabout preprocessing`
- Step1-Step6 主逻辑无需改动，因为后续语义读取本就优先使用 `working_mainnodeid`
- 本轮同时修正 accepted 契约文档与单测
