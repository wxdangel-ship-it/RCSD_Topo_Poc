# T08 模块规格：SWSD / RCSD 数据预处理

## 1. 模块定位

T08 是项目正式预处理模块，负责 SWSD / RCSD 输入数据的格式转换、类型显性化、质量检查、字段修复、restriction / Laneinfo 显性化和 RCSD 清理。T08 为 T01、T03、T04、T05、T06、T09 提供规范输入，是当前主链的前置数据治理层。

## 2. 业务目标

- 将多格式空间数据转换为项目可消费的 GPKG / GeoJSON。
- 补齐 SWSD Road / Node 的 `patch_id / kind / kind_2 / grade_2` 等下游基础字段。
- 把历史 T01/T02/T04 中的部分属性修复与预处理职责收敛到正式预处理模块。
- 将 SWSD restriction 与 Laneinfo arrow 显性化，支撑 T09 通行规则恢复。
- 清理 RCSDNode / RCSDRoad，保证下游 relation 与 Segment 替换输入可解释。

## 3. 当前范围

### 3.1 正式支持

- Tool1：基础矢量格式转换。
- Tool2：Road patch / kind 预处理与 `17` 事件 Road 输出。
- Tool3：Nodes `kind_2 / grade_2` 初始化与环岛聚合。
- Tool4：路口类型修复。
- Tool5：复杂路口预处理与错误 1 对多处理。
- Tool6：Nodes 类型质检。
- Tool7：交通限制显性化。
- Tool8：Laneinfo arrow 显性化。
- Tool9：RCSD 数据清理。

### 3.2 当前非目标

- 不执行 T01 Segment 构建。
- 不执行 T03/T04 虚拟路口构面。
- 不生产 T05 relation。
- 不执行 T06 Segment 替换。
- 不在 Tool6 中直接修复输入；Tool6 只输出人工质检候选。
- 不原地修改输入文件。

## 4. 上下游关系

| 方向 | 模块 / 数据 | 关系 |
|---|---|---|
| 上游 | 原始 SWSD / RCSD / patch / lane / restriction 数据 | 提供格式和字段不统一的基础输入。 |
| 下游 | T01 | 消费预处理后的 SWSD Nodes/Roads 构建 Segment。 |
| 下游 | T03 / T04 / T05 / T06 | 消费预处理后的 Road/Node、Road surface、RCSD 清理结果和字段语义。 |
| 下游 | T09 | 消费 Tool7 restriction 与 Tool8 arrow 作为通行规则证据。 |

## 5. 输入

| 输入 | 用途 |
|---|---|
| SHP / GeoJSON / GPKG | Tool1 格式转换输入。 |
| SWSD Road / Node | Tool2-6 类型、拓扑、修复和质检输入。 |
| Patch Road / Raw Kind Road | Tool2 补充 `patch_id` 与原始 `kind`。 |
| RCSDIntersection | Tool5 错误 1 对多识别与处理输入。 |
| SW C 表 | Tool7 restriction 显性化输入。 |
| SW Laneinfo | Tool8 arrow 显性化输入。 |
| RCSDNode / RCSDRoad / 道路面 | Tool9 RCSD 清理输入。 |

## 6. 输出

| 输出 | 用途 |
|---|---|
| `*.gpkg / *.geojson`（Tool1 同 stem 换后缀） | 基础格式转换成果。 |
| `*_tool2.gpkg/json` | Road patch、kind enrich、事件 Road 输出。 |
| `*_tool3.gpkg/json` | 初始化并聚合后的 Nodes。 |
| `*_tool4.gpkg/json` | 路口类型修复后的 Nodes/Roads/audit。 |
| `*_tool5.gpkg/json` | 复杂路口预处理与 1 对多修复成果。 |
| `node_error_tool6.*` | 人工质检候选。 |
| `sw_restriction_tool7.*` | 显性 restriction 证据。 |
| `sw_arrow_tool8.*` | 显性 arrow 证据。 |
| `rcsdnode_clean_tool9 / rcsdroad_clean_tool9` | 清理后的 RCSD 输入。 |

## 7. 关键业务步骤

| 工具 | 业务说明 |
|---|---|
| Tool1 | 将 SHP / GeoJSON / GPKG 转成下游可消费格式，并保留 CRS 与 summary。 |
| Tool2 | 为 Road 补 `patch_id / kind`，输出未命中 Road，并剔出 `17` 事件 Road。 |
| Tool3 | 初始化 `kind_2 / grade_2`，按 `roadtype bit3` 聚合环岛 mainnode。 |
| Tool4 | 根据入度 / 出度、提前右转 / 辅路豁免和 Tool6 人工确认结果修复路口类型。 |
| Tool5 | 聚合复杂分歧 / 合流链路，并处理 RCSDIntersection 一对多错误路口。 |
| Tool6 | 输出连续分合流和交叉 / T 型错误候选，供人工确认后被 Tool4 消费。 |
| Tool7 | 将 `CondType=1` restriction 转成显性 LineString。 |
| Tool8 | 将 Laneinfo arrow 聚合为 Road 方向级 arrow LineString。 |
| Tool9 | 基于道路面过滤 RCSDNode 语义组与 RCSDRoad 起终点拓扑。 |

## 8. 什么是对

- 除 Tool1 转换成果外，所有 T08 输出文件名在扩展名前以 `_toolX` 结尾；Tool1 转换成果允许同 stem 换后缀。
- Tool3 不把单 node 环岛组误写为 `kind_2=64`。
- Tool4/Tool5/Tool9 均使用 copy-on-write，不回写输入。
- Tool6 只输出质检候选，不直接修复数据。
- Tool7/Tool8 保留原始业务字段并显性化几何证据。
- Tool9 删除 RCSD 语义组必须按组内所有 node 是否被道路面覆盖 / 包含判定。

## 9. 什么是错

- 不记录 CRS 或字段缺失就继续输出。
- 用 Tool6 结果绕过人工确认直接修复。
- 修改输入文件而不是输出新文件。
- 把 restriction / arrow 显性化结果直接解释成 T09 最终通行规则。
- 在 RCSD 清理中只按单 node 保留而破坏 `mainnodeid` 语义组。

## 10. 当前治理缺口

- T08 文档已收敛为模块级 01-06 主结构，后续新增工具说明应优先落入 `03-solution-strategy.md`、`04-evidence-and-audit.md` 或 `06-risks-and-technical-debt.md`。
- Tool1-9 需要持续保证脚本入口、接口契约、代码实现和文档描述同步。
