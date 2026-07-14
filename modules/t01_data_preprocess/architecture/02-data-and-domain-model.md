# 02 数据与领域模型

## 1. 上下游数据关系

T01 的输入是 T08 预处理后的 SWSD `nodes / roads`。T01 在本模块内部复制并刷新 working layers，不直接改写原始输入。最终输出的 SWSD Segment 被 T06 用作 Segment 替换的 SWSD 侧承载，被 T09 用作 SWSD Arm 与通行规则恢复的承载关系之一。

## 2. 核心业务对象

| 对象 | 业务含义 |
|---|---|
| `working nodes` | 输入 node 的工作副本，承载当前构段语义。 |
| `working roads` | 输入 road 的工作副本，承载 Segment 归属和 `sgrade`。 |
| semantic junction | 由 `mainnodeid` 或 node 自身表达的语义路口，是 Segment 起终点和内部节点判断基础。 |
| pair candidate | Step1 搜出的候选端点组合，只表示可能构段，不表示 Segment 已成立。 |
| validated pair | Step2 或后续 residual 阶段确认成立的端点组合。 |
| trunk | validated pair 的主干追溯路径。 |
| segment body | 当前 pair 可解释归属的 road body，不包含其它 pair trunk 或非本 pair 的旁路。 |
| oneway segment | Step5C 后补齐的单向或受控 dead-end / fallback Segment。 |
| final segment | Step6 按 `segmentid` 聚合后的正式输出。 |

## 3. 关键字段语义

- `grade_2 / kind_2` 是 T01 后续业务判断的当前语义字段；初始化来自 `grade / kind`，随后由构段结果滚动刷新。
- `closed_con` 是 T01 强规则使用的规范字段；`closed_connect` 是已确认等价的原始输入别名，由 T08 归一，不形成独立语义。
- 原始 `grade / kind` 保留为输入事实，不直接替代 `grade_2 / kind_2` 进入后续强规则。
- `Road.kind` 已确认可在局部续行中读取前两位道路等级；字段缺失、不可解析或无同等级候选时，不通过几何形态反推道路等级。
- `formway = 128` 表示右转专用道，在 Step1-Step5C 构段图中被排除。
- `road_kind = 1` 在 SWSD 中代表封闭式道路，多数场景为高速 / 高速相关道路；双向 Step1-Step5C 排除，Step5 后单向补段才允许进入受控候选。
- `segmentid` 表达 road 所属 Segment，Step6 以它聚合正式 Segment。
- `sgrade` 表达 Segment 构段阶段和方向属性，必须能从构段来源解释。

## 4. 数据流

1. 输入 `nodes / roads` 被复制为 working layers。
2. 环岛预处理与 bootstrap retyping 修正 Step1 前的当前语义。
3. Step1-Step5C 在 working layers 上构建双向 Segment，并在每轮结束后刷新 `grade_2 / kind_2 / segmentid / sgrade`。
4. 单向补段只处理 Step5C 后仍未构段的 road。
5. Step6 聚合 `segment.gpkg`，同时输出内部节点、冲突和未构段 road 审计。

## 5. 领域边界

T01 的 Segment 是 SWSD 侧道路承载层，不等同于 RCSD Segment，也不等同于路口 1:1 关系。T01 可以为下游提供 `pair_nodes / junc_nodes / roads / sgrade`，但不负责决定 RCSD 与 SWSD 的替换关系是否成立。
