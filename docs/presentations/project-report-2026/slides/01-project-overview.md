# 第一部分：项目总览

本章固定 4 页。目标是在开场阶段快速建立共识：项目的业务目标、核心效果、总体链路和后续演进方向。

## 第 1 页：一句话结论与核心价值

### 页面标题

保留全量通行能力，替换为 RCSD 高精度骨架路网

### 页面副标题

以 SWSD 道路结构为牵引，通过真实证据锚定 RCSD，完成可审计、可追溯、可持续优化的全量融合。

### 页面主文案

本项目的融合本质，不是简单叠加两套数据，也不是直接用 RCSD 反推道路结构。

项目先以 SWSD 构建路口、路段、Movement 的道路结构认知；再通过路口面、道路面、导流带等真实证据建立 SWSD-RCSD 路口锚定；最后以 SWSD Segment 和锚定路口为牵引构建 RCSD Segment，在保留全量拓扑通行能力的前提下，将承载骨架替换为 RCSD 高精度路网。

### 核心价值

- **结构牵引**：以 SWSD 建立路口、路段、Movement，不依赖 RCSD 直接反推结构。
- **证据锚定**：通过路口面、道路面、导流带支撑 SWSD-RCSD 路口对应关系。
- **安全替换**：以通行能力保留为底线，完成 RCSD Segment 构建与 F-RCSD 输出。
- **能力延展**：在替换后的高精度骨架上恢复 restriction，并支撑后续高阶要素构建。

### 建议图示

```text
SWSD 道路结构
路口 / 路段 / Movement
        ↓
真实空间证据
路口面 / 道路面 / 导流带
        ↓
SWSD-RCSD 路口锚定
        ↓
RCSD Segment 构建与安全替换
        ↓
RCSD 高精度骨架路网 + 全量通行能力保留
```

### 数据占位

- 处理范围：`[待补：数据批次 / 城市 / case 范围 / 路口或道路规模]`
- 交付成果：`[待补：全量 run root / summary / 审计产物]`
- 核心指标：`[待补：锚定成功、可替换 Segment、F-RCSD 输出、restriction 恢复]`

## 第 2 页：关键成果摘要

### 页面标题

关键成果摘要：从结构认知到高精度骨架替换的闭环能力

### 页面主结论

项目已经形成从 SWSD 结构构建、真实证据锚定、RCSD Segment 替换，到 restriction 恢复和质量审计的完整业务闭环。当前缺少的是正式汇报用的最终统计数字，而不是能力链路本身。

### 页面正文

| 成果层级 | 已形成能力 | 后续填充指标 |
|---|---|---|
| 输入治理 | SWSD / RCSD / 真实空间证据进入统一预处理和质量显性化链路。 | 输入对象规模、字段修复、质量问题数量 |
| SWSD 结构构建 | 以 SWSD Road/Node 构建路口、路段、Movement 和可替换 Segment。 | Segment 数量、语义路口数量、未构段 road |
| 真实证据锚定 | 通过已有路口面、道路面、导流带和虚拟构面建立 SWSD-RCSD 路口锚定。 | relation 成功、blocked、review-only、cardinality error |
| 骨架替换 | 以 SWSD Segment 和锚定路口牵引 RCSD Segment 构建，在通行能力保留约束下输出 F-RCSD。 | replaceable、retained、failed、problem registry 分类 |
| 通行恢复 | 在 F-RCSD 上恢复 SWSD restriction，验证替换后通行语义可承接。 | restriction 恢复数量、跳过原因、审计结果 |
| 质量闭环 | T10 组织 run manifest、T06 funnel、visual check、feedback 和 case replay。 | 已分类问题、可回流问题、待人工确认问题 |

### Dashboard 指标卡

```text
输入规模：待补
SWSD Segment / 语义路口：待补
SWSD-RCSD 锚定成功：待补
F-RCSD 替换 / 保留 / 失败：待补
restriction 恢复：待补
质量问题闭环：待补
```

### 表达边界

`Movement` 是结构能力，不作为本页展示指标。正式展示指标优先使用 `restriction` 恢复、替换结果和质量闭环结果。

## 第 3 页：总体业务流程

### 页面标题

总体业务流程：SWSD 结构牵引，真实证据锚定，RCSD 骨架替换

### 页面主结论

项目的关键顺序是：先用 SWSD 建立道路结构，再用真实证据锚定 RCSD，最后以 SWSD Segment 和锚定路口牵引 RCSD Segment 构建与替换。这个顺序保证了高精度骨架替换不会以丢失拓扑通行能力为代价。

### 页面流程

```text
SWSD / RCSD / 真实空间证据输入
        ↓
T08 输入预处理与质量显性化
        ↓
T01 以 SWSD 构建路口、路段、Movement / Segment
        ↓
T07 / T03 / T04 基于路口面、道路面、导流带建立 SWSD-RCSD 锚定
        ↓
T05 汇总多来源证据，发布统一 SWSD-RCSD relation 主表
        ↓
T06 以 SWSD Segment + 锚定路口牵引 RCSD Segment 构建与 replacement plan
        ↓
T09 在 F-RCSD 上恢复 restriction，验证通行能力可承接
        ↓
T10 组织全链路 manifest、漏斗、反馈和 case replay
```

### 页面强调语

> relation 是替换的必要前提，但不是替换成功的充分条件。T06 必须继续检查 RCSD 道路、方向、端点、拓扑、surface 和通行能力保留风险。

### 模块角色摘要

| 环节 | 模块 | 汇报表达 |
|---|---|---|
| 输入准备 | T08 | 让 SWSD、RCSD 和真实证据可被下游稳定消费。 |
| 结构基础 | T01 | 以 SWSD 构建可替换 Segment 和道路结构主线。 |
| 路口锚定 | T07 / T03 / T04 | 用真实证据建立已有路口、常规路口和复杂路口锚定。 |
| 关系发布 | T05 | 汇总多来源证据，输出统一 relation 主表。 |
| 骨架替换 | T06 | 构建 RCSD Segment，发布 replacement plan，输出 F-RCSD。 |
| 通行恢复 | T09 | 恢复 restriction，证明替换后通行语义可承接。 |
| 编排审计 | T10 | 提供全链路证据、质量漏斗和问题回流。 |

## 第 4 页：项目演进趋势

### 页面标题

项目演进趋势：从全量融合到持续构图与质量优化

### 页面主结论

当前阶段采用一次性全量融合，是为了形成统一 baseline、验证质量漏斗和建立可复核结果。由于项目已经形成 SWSD 结构牵引、真实证据锚定、通行能力保留约束和问题反馈机制，后续可以平滑演进为局部更新和持续质量优化。

### 三阶段演进

| 阶段 | 当前定位 | 关键能力 |
|---|---|---|
| 一次性全量融合 | 建立统一 baseline，验证端到端融合链路。 | SWSD 结构构建、路口锚定、RCSD Segment 替换、restriction 恢复、全链路审计 |
| 局部更新能力 | 按区域、路口、道路变更范围或质量问题触发局部重算。 | case package、局部 replay、T06 feedback、baseline 对照、问题分流 |
| 长期结构底座 | 在稳定道路结构层上构建更高阶的道路要素。 | Movement、RoadNextRoad、通行组织、禁限行、车道级关系、Skill 反馈 |

### 长期价值

- 全量融合建立可信 baseline，局部更新降低后续维护成本。
- RCSD 高精度骨架承接 SWSD 拓扑通行能力，为高阶要素提供稳定底座。
- restriction 恢复是当前可展示、可审计的通行能力成果。
- 大模型 Skill 反馈机制沉淀质量问题、根因分析和修复经验，支撑长期优化。

### 数据占位

- 当前 baseline：`[待补：run root / 版本 / 日期]`
- 局部更新最小单元：`[待确认：semantic junction / Segment / case package / patch]`
- 高阶要素优先级：`[待确认：restriction / Laneinfo / RoadNextRoad / 车道级关系]`
- Skill 反馈案例：`[待补：典型质量问题 -> 根因 -> 修复或规则沉淀]`
