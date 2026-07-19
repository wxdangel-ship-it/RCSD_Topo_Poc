# RCSD_Topo_Poc 项目级需求详细版

## 1. 文档定位

本文档是项目级需求详细版，用于解释 `SPEC.md` 中简版需求的业务背景、范围、模块分工、质量边界和改进路线。根目录 `SPEC.md` 只保留简洁需求入口；跨模块方案如何落地见 `docs/architecture/03-solution-strategy.md`；模块内部需求见 `modules/<module>/SPEC.md`，模块架构设计见 `modules/<module>/architecture/03-solution-strategy.md`，稳定接口见 `INTERFACE_CONTRACT.md`。

## 2. 业务背景

项目要解决的问题是：SWSD 更贴近现场道路语义和通行规则，RCSD 更贴近场景路网承载，两套数据在道路切分、节点归组、方向表达、提前右转、路口内部短连接和局部缺失上存在差异。项目需要把 SWSD 的现场语义能力迁移到 RCSD / F-RCSD 承载网络中，并让每一步都有可追溯的证据和审计。

因此项目采用 relation-first 的融合思路：先建立可信的 SWSD-RCSD 语义路口关系，再沿路口之间的 Segment 做承载替换。路口 relation 是 Segment 替换的前提，但不是替换成功的充分条件；T06 必须继续检查 RCSD 道路、方向、端点、拓扑和 surface 证据，防止错误替换。

## 3. 业务链详细需求

### 3.1 输入准备层

T08 负责把 SWSD / RCSD 原始输入整理成下游可消费的数据。它需要处理格式转换、Road/Node 类型归一、restriction / Laneinfo 显性化、RCSD 清理和质量问题暴露。T08 的输出不直接代表替换成功，但决定 T01、T03、T04、T05、T06、T09 是否能稳定消费同一套输入事实。

### 3.2 Segment 基础层

T01 负责将 SWSD Road/Node 组织成 Segment。Segment 需要保留 pair 节点、junc 节点、road body、方向和等级语义，使 T06 能以“两个语义路口之间的道路连续单元”为替换对象，而不是直接处理零散 Road。

### 3.3 路口关系层

T07、T03、T04、T05 都服务于 SWSD-RCSD 语义路口关系构建，但分工不同：

- T07 处理已有路口面 / RCSDIntersection 能直接说明关系的路口，并保留可选兼容 relation 补锚能力；该补锚来自显式提供的早期或外部 `intersection_match_all` 兼容关系，不是 T05 之后默认重锚。
- T03 处理交叉路口和 T 型路口，通过合法道路面空间、RCSD 关联和负向约束构建虚拟锚定面。
- T04 处理分歧、合流、连续分歧 / 合流和复杂路口，通过事实事件解释、支撑域和最终发布结果形成复杂路口锚定证据。
- T05 将 T07/T03/T04 的 surface 与 relation evidence 汇总为统一的 `intersection_match_all`，并对 RCSDRoad / RCSDNode 做 copy-on-write junctionization。

这一层的业务目标是让每个 SWSD 语义路口在下游拥有唯一、可解释、可审计的 RCSD 关系基点或明确失败原因。

### 3.4 Segment 替换层

T06 的原始目标是基于 T01 Segment 与 T05 relation 将 SWSD Segment 替换为 RCSD Segment。端到端 Case 修复后，T06 的实际职责已经扩展为替换质量承接：

- relation 缺失或疑似错锚时，T06 需要输出 buffer-only probe、repair candidates 和 problem registry，而不是静默替换。
- RCSDRoad 与 SWSD Segment 切分不一致时，T06 需要用 buffer corridor、方向、连通和覆盖审计证明替换范围。
- pair anchor 错误、端点缺失或两端坍缩到同一 RCSD 语义路口时，T06 只能在高置信、方向和几何审计通过的条件下做当前 Segment 内重试，不能回写 T05 relation。
- 提前右转、内部调头口、road-only split 和 detached junc 可能导致主通道可替换但局部 carrier 仍需保留；这类混源必须通过状态和风险标记表达，不能混入正式 RCSD 替换道路清单。
- T03/T04/T05/T07 surface 可以帮助节点语义闭合；对 retained-junction 20m 距离 gate，只能在 surface 1:1 pass 或原始 pair endpoint 映射可解释时降级为人工审计风险，并必须经过 topology 回退。它不能绕过 T04 reject、Patch 冲突、多候选冲突或 Step2 replacement plan。

T06 的核心边界是“先证明可替换，再执行替换”：Step2 发布 replacement plan 和 problem registry，Step3 只执行 plan，并用 source 边界、提前右转后处理、surface topology closure 和 topology connectivity audit 保护最终 F-RCSD。

### 3.5 人工审计层

T11 在 T10 正式工作流中位于 T06 与 T09 之间，读取当前 Case/full run 的 T05/T06/T10 证据，输出 relation repair candidates、人工模板和 summary。T11 是人工审计层：不回写 T05/T06，不改变 T09 输入，也不把候选提升为人工确认或替换白名单。

### 3.6 通行恢复层

T09 在 T06 输出的 F-RCSD 承载关系上恢复 SWSD 现场通行规则。当前 T09 主要依赖 SWSD restriction / Laneinfo，后续需要结合 RCSD Laneinfo 和轨迹通行证据继续增强。

### 3.6A F-RCSD 质量审计层

T12 面向通过 1V1 匹配技术融合生成的原始 F-RCSD，不把它解释为 T06 Segment 替换结果。T12 以“SWSD 与 1V1 F-RCSD 的拓扑通行性应等价”为待验证质量假设，复用 T06 的 ID、方向、canonical node、carrier graph 和局部 portal 证据语义，检查已锚定 Segment 两端在目标承载网是否存在可解释通行路径。`RCSDIntersection` 是 T07/T10 标准输入和人工确定的现实路口证据；T05/T06 只提供交叉解释证据，不替代 T12 对原始目标网的判断。

T12 必须分离 candidate、confirmed、excluded 和 optional review override。candidate 不是正式质量问题；只有在原始 FRCSD Road endpoint 图上证明 SWSD 必需方向缺少等价 carrier，并通过 `RCSDIntersection` 标准路口 portal、锚点可信度、方向和几何门禁的记录，才能自动进入 confirmed 层。canonical `mainNodeId/subNodeId` 图只用于宽召回和交叉解释，不得通过零成本节点折叠补出正式 carrier。外部 review decisions 只作可选 QA 覆盖，不再是 confirmed 的前置条件。排除原因必须可追溯，任何阶段都不得修改输入几何、自动补路或 silent fix。

### 3.7 编排与证据层

T10 负责组织端到端 Case package、Case replay、full pipeline manifest、T06 funnel、可选 T12 quality audit、T11 candidate audit、visual check 和 feedback package。T10 不定义或改写 T01-T09 / T11 / T12 的算法规则，不把 T06 feedback 直接作为 Step3 替换白名单。T10 v1 Case runner 默认在 T06 后、T09 前执行 T11；显式启用并提供原始 1V1 F-RCSD 时在 T11 后、T09 前执行 T12。两者都不改变 T06 到 T09 的业务 handoff。T10 提供固定 `RUN_T08=0 / RUN_T12=1` 的 F-RCSD 质量检查专用流水线；普通 Case runner 不调用 T08，通用内网全量总控仍可把 T08 作为独立前置阶段串入。

## 4. 模块责任边界

| 模块 | 详细责任 |
|---|---|
| T00 | 支撑工具集合，历史一次性预处理能力主要已被 T08 吸收，保留追溯入口。 |
| T01 | SWSD Segment 构建，输出 T06 替换和 T09 通行建模基础。 |
| T02 | Retired 历史模块，能力已由 T07 / T03 / T04 / T08 承接。 |
| T03 | 常规交叉 / T 型虚拟锚定，输出 T05 可消费 relation evidence。 |
| T04 | 分歧 / 合流 / 复杂路口虚拟锚定，输出 accepted/rejected、surface、relation evidence 和审计。 |
| T05 | 统一融合 T07/T03/T04 关系，发布 SWSD-RCSD 语义路口主表和 copy-on-write RCSD 输出。 |
| T06 | 在 relation 基础上做 Segment 替换可行性审查、执行和拓扑审计。 |
| T07 | 已有路口面 1:1 锚定与可选兼容 relation 补锚，不处理 Segment，不生成虚拟路口面。 |
| T08 | SWSD / RCSD 预处理、质检和修复前置模块。 |
| T09 | F-RCSD 上的通行规则恢复。 |
| T10 | 端到端编排与 Case 证据组织，不替代 T01-T09 / T11 算法。 |
| T11 | T06 后、T09 前的人工 relation 修复候选审计；不回写业务产物。 |
| T12 | 原始 1V1 F-RCSD 质量审计；验证 SWSD 可达性等价假设，以 raw endpoint topology、标准路口 portal 和锚点可信度自动发布高置信问题与排除证据，人工 review 仅作可选 QA 覆盖，不执行修复。 |
| P01 | 异构路口通行能力 POC，不作为 T09 正式替代契约。 |
| P02 | 武汉局部人工锚定实验编排与证据收口；复用 T08/T01/T05/T06，不替代这些模块的正式业务契约。 |

## 5. 质量与验收口径

项目级质量要求关注跨模块结果是否可解释、可追溯、可验证：

- CRS 和坐标变换必须明确记录，不允许用隐式默认 CRS 掩盖问题。
- 拓扑一致性不能靠 silent fix，必须输出审计和失败原因。
- 几何结果必须能解释其业务语义，例如路口面、Segment corridor、surface closure 和 carrier 保留边界。
- 每个模块 handoff 必须能定位输入、输出、参数、运行环境、summary 和 audit。
- T06 / T10 等端到端结果不能只证明代码路径可运行，还要能证明具体 run root 的完成态和关键输出存在。

## 6. 非目标

- 项目级需求不展开模块内部完整参数表、字段值域和实现步骤。
- T10 不修复上游算法，不替代 T01-T09 / T11 / T12 的模块契约。
- T06 不用 problem registry 或 surface fallback 绕过 replacement plan。
- P01 不替代 T09 正式通行规则恢复契约。
- P02 不伪造缺失的 T07/T03/T04 道路面锚定成果，不把局部实验结论直接提升为全量口径。
- T02 不继续承接新业务需求。

## 7. 改进路线

1. Relation 质量产品化：T07/T03/T04/T05 继续稳定输出成功、失败、fallback、review-only、blocked 和 upstream-needed 状态，减少 T06 重复解释上游问题。
2. T06 问题回流闭环：problem registry 中可自动消费的问题进入 T10 feedback 和 T05，可疑或超边界问题进入人工复核或上游任务。
3. F-RCSD 自动 QA：T06 Step3 结果继续由 T06 正式审计；原始 1V1 F-RCSD 由 T12 检查 road-node integrity、raw endpoint 方向可达性、标准路口 portal、局部替代路径和 DriveZone 证据，并自动发布高置信问题；人工 review 仅作可选 QA 覆盖。
4. 通行能力增强：T09 后续引入 RCSD Laneinfo 和轨迹证据；P01 Arm / RoadNextRoad 经验可作为正式化前参考。
5. 文档层级收敛：根目录只保留简洁入口和简版需求，详细需求、架构策略、治理盘点和模块契约下沉到对应目录。
