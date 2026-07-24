# P04 架构：风险与技术债

## 1. 主要风险

| 风险 | 影响 | 控制 |
|---|---|---|
| 旧Road-owner逻辑渗入新版本 | 名为Segment-first，实际仍按SWSD Road决策 | 独立`segment_first_*`文件族；T01 Segment为一级索引；contract测试禁止parent Road顶层owner |
| 继续使用SWSD纵向reference | 新Road偏SWSD、扭曲、精度价值不足 | built Road只含observed/constrained；独立QA检查SWSD splice为0 |
| 部分支持变成Road内raw SWSD拼接 | 接缝折角、断裂和虚假高精 | 每个正式Road identity原子；built缺口只constrained；允许的partial member必须拆为互不重叠的built与`swsd_retained_partial` Road并共享transition Node |
| 方向Road与双向retained重复 | 重复carrier和错误拓扑 | carrier planning先于geometry；专门重叠hard gate |
| T07/T03/T04状态误读 | review/relation被冒充accepted | 只消费正式主层和值域；contract测试；T07冲突优先 |
| 把T07端点优先级扩散成T04拓扑覆盖 | complex范围和显式Movement被人工面意外改写 | 拆分`junction_source`与`surface_source`；T07只控制端点面，T04继续控制complex拓扑 |
| 用关系距离代替Road实际入面 | THROUGH在路口侧方被横向切断或Road端点停在buffer | accepted polygon场景只在Road实际穿入内缩surface时切分；最终Node对原始面执行严格`contains` hard gate；仅`swsd_retained`点且同一T01 Segment正式THROUGH lineage唯一时允许不移动几何的投影细分 |
| mainnode直接全连接 | 立体误聚合或复杂路口伪连接 | 只从实际shared node编译；错误mainnode聚合Review/fallback |
| ordinary端点整体折叠到中值Node或补造中心星形Road | 高精骨架扭曲、路口放射线密集并偏离SWSD/RCSD原生结构 | 保留分布式高精portal；同组mainnode表达路口身份；ordinary语义RoadNextRoad表达默认PhysicalMovement；逐Road Access hard gate |
| 把“两个方向”误实现为固定两条长Road | 吞并LaneGroup边界、局部物理Node和证据变化，Road—Lane关系难以解释 | 以方向主干链验收，允许可追溯细分Road；链内共享实际Node并做端到端连续性门禁 |
| junc_nodes被可选裁剪 | 真实侧向连接消失 | relation与最终拓扑hard required；仅显式detached/exempt例外 |
| LaneTopo owner过滤遗漏局部结构 | 调头/短连接静默消失 | same/cross owner统一分类；Patch已有局部Road同步消费 |
| 强证据不足时追求替换率 | 伪造高精Road | 替换率只作观察；hard gate失败完整retained |
| full RCSD被当目标真值 | 重新继承旧RCSD质量问题 | 仅锚定/fallback候选；Patch强证据验证 |
| 输入字段语义不明 | 样本规则污染业务 | observed-only；正式字典/契约前不进强规则 |
| ID不稳定 | 跨Patch和重复运行无法合并 | 数据规格+稳定业务seed；顺序扰动测试 |
| QGIS目视替代机器QA | 漏掉全量拓扑/字段问题 | 发布后独立QA硬门禁；QGIS仅补充人工语义审计 |
| 单Case过拟合 | 指标在其它范围失效 | 阈值保留POC属性、参数化、逐证据审计；后续多Case扩展 |

## 2. 业务范围风险

### 2.1 无SWSD与现实结构变化

架构保留RealityChangeClue→simple Road→temporary Segment→normalization流程，但当前不实现无SWSD全图构建或自动改写T01结构。不得把线索直接变成正式Segment。

### 2.2 调头口和内部短连接

当前只消费Patch已有且证据支持的局部Road。缺失恢复需独立策略；本轮召回率不能解释为完整局部结构生产能力。

### 2.3 Restriction/Laneinfo

RoadNextRoad表达物理可达，不等于合法通行。T09语义未接入前不得把默认ordinary全连接解释为全部转向合法。

## 3. 输入技术债

- Vector枚举字典仍不完整。
- RoadSplit正式语义待确认。
- 完整RCSD与Patch RCSD缺少显式Patch关联，只能通过锚定上下文和同版本证据使用。
- RCSD ID与source规格必须在实现preflight核对。
- Patch资料缺失较多，高精覆盖率不能成为唯一验收指标。

## 4. 几何技术债

- constrained completion的距离、曲率、跨度和道路面容差需真实数据标定。
- Lane/Boundary中心走廊在主辅路、渠化和局部拓宽场景仍需人工审计。
- ordinary Junction已hard gate逐Road Access、portal支撑和内部carrier完整性；portal到中心的最优曲线、车道级渠化形态仍是后续几何标准化能力。

## 5. 拓扑技术债

- complex Junction内部Road/Node编译依赖T04和Patch证据，仍需用真实样本验证。
- Patch已有调头/短连接的Road/Node ID继承可能存在数据规格差异。
- PhysicalMovement到T09合法性的完整桥接不在当前范围。

## 6. 治理技术债

- 当前P04历史文件和source-of-truth尚未形成提交基线，实施中必须保留工作区现有成果。
- P04仍无官方入口；当前仅研究callable。
- `docs/repository-metadata/path-conventions.md`尚未建立。
- 当前测试仍以单Case/有限Patch为主，生产正式化必须另行SpecKit。

## 7. 不可接受的债务转移

- 不允许为P04修改T01–T12正式接口。
- 不允许把未知语义写成强规则并留给后续修复。
- 不允许用silent snap、geometry buffer或mainnode笛卡尔连接隐藏拓扑失败。
- 不允许把soft Review计数清零当质量提升。
- 不允许在缺少independent QA和人工审计时宣布业务完成。

## 8. 历史版本保护

M1/M2、冻结V2和V3实证继续作为历史对照。新版本可复用通用写出、CRS、hash、QGIS和QA能力，但不得改写旧输出合同、run ID、结果文档或历史指标含义。
