# 03 上下文与范围

## 当前上下文
- T01 解决的是普通道路网络上的双向 Segment 构建问题，并在 `Step5` 之后提供单向补段 continuation；单向补段可覆盖 `road_kind = 1` 的封闭式 / 高速相关 road，并在该 continuation 内受控补齐 dead-end leaf Segment。
- 它不是最终拓扑治理终点，而是后续模块消费 `refreshed nodes.gpkg / roads.gpkg / segment.gpkg` 的基础模块。

## 当前 in-scope
- `working bootstrap`
- `roundabout preprocessing`
- `Step1`
- `Step2`
- `Step3 refresh`
- `Step4`
- `Step5A / Step5B / Step5C`
- `Step5` 后单向补段 continuation
  - 单向补段中 `road_kind = 1` 的封闭式 / 高速相关 road
  - 单向补段中 `kind_2 = 128` 的复杂分歧 / 合流路口 terminate
  - dead-end leaf Segment：单条双向 road 或两条方向互补单向 road bundle，一端为合法语义端点，另一端为 leaf node
- `Step6`
- active freeze baseline 的非回退检查

## 当前 out-of-scope
- 封闭式道路场景
- 脱离 `Step5` refreshed 结果的独立单向构段体系
- Step6 之后更完整的最终拓扑治理闭环
- 以临时样例基线替代 accepted baseline
