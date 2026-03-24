# 03 上下文与范围

## 当前上下文
- T01 解决的是普通道路网络上的双向 Segment 构建问题。
- 它不是最终拓扑治理终点，而是后续模块消费 `refreshed nodes / roads / segment.geojson` 的基础模块。

## 当前 in-scope
- `working bootstrap`
- `roundabout preprocessing`
- `Step1`
- `Step2`
- `Step3 refresh`
- `Step4`
- `Step5A / Step5B / Step5C`
- `Step6`
- 临时最终 Segment 基线治理与非回退检查

## 当前 out-of-scope
- 封闭式道路场景
- 单向 Segment
- Step6 之后更完整的最终拓扑治理闭环
- 以临时样例基线替代 accepted baseline
