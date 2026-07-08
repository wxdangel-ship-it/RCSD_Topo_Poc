# 05 质量要求

## 1. 业务可解释性

T01 输出的每个 Segment 都必须能解释端点来源、road body 归属、构段阶段、方向属性和冲突状态。Step1 candidate 不能被当作成立 Segment；只有 validated pair、单向补段或受控 fallback 才能进入最终构段结果。

Step6 前形态控制造成的 Segment 拆分必须能解释到内部语义节点、转角或道路等级证据；不得以长度作为唯一理由拆分。

## 2. GIS 与拓扑要求

- CRS 必须在输入、working layers 和输出之间保持一致；需要坐标变换时必须显式记录，不允许 silent fix。
- road 与 node 的拓扑连接必须可解释；缺失端点、孤立 road、非法几何不能被静默吞掉。
- `formway = 128` 右转专用道在 Step1-Step5C 中必须一致过滤。
- `mainnodeid = NULL` 不等于“不是路口”；在规则满足时 node 自身可作为独立语义路口。
- QGIS 兼容的 GPKG 输出必须保留旧版 OGR provider 过滤后的要素计数一致性。

## 3. 回归质量

- active freeze baseline 是非回退闸门，不得在未授权时更新。
- `PASS_LOCKED` 样例不得回退。
- `FAIL_TARGET` 的变化必须记录前后差异，不能用最终成功率掩盖局部语义倒退。
- 单向补段结果与双向 accepted baseline 的判断口径必须分开。

## 4. 诊断质量

`debug=true` 可以增加中间阶段、审计图层和性能诊断，但不得改变最终业务结果。trunk gate、side gate、T-junction gate、endpoint pool、same-stage arbitration、segment shape control 的拒绝 / 拆分原因必须能在证据中定位。

## 5. 性能要求

全量运行必须关注 Step2 same-stage arbitration、trunk search budget、candidate retention 和 GPKG 写出性能。性能优化不能改变 candidate search、validated pair、segment body 和最终 `segment.gpkg` 的业务语义。
