# Feature Specification: 外部数据字段名统一归一化

**Feature Branch**: `codex/004-field-name-normalization`
**Created**: 2026-07-18
**Status**: Ready for implementation
**Input**: 用户要求统一自查并修复仓库中因字段名大小写差异导致的错误，首要问题为 T03/T04 读取 1V1 FRCSD 的 `snodeId/enodeId/formWay`。

## User Scenarios & Testing

### User Story 1 - 等价规格数据可进入主链 (Priority: P1)

作为端到端执行者，我希望字段名仅大小写不同的 SWSD、RCSD、FRCSD 数据被视为同一逻辑规格，使 T03 与 T04 不再因为 `snodeId` 和 `snodeid` 的差异产生漏解析或失败。

**Why this priority**: 当前 T03 会静默跳过道路端点，T04 会在必填字段校验处失败，直接阻断质量检查主链。

**Independent Test**: 使用同一组道路记录分别以小写和 camelCase 字段名运行 T03/T04 解析，结果中的道路 ID、端点、方向和拓扑邻接必须一致。

**Acceptance Scenarios**:

1. **Given** FRCSD 道路包含 `snodeId/enodeId/formWay`，**When** T03 构建道路记录及邻接，**Then** 端点与 `formway` 均被读取且邻接不为空。
2. **Given** FRCSD 道路包含 `snodeId/enodeId`，**When** T04 校验必填道路字段，**Then** 不因字段名大小写差异报 `missing required fields`。
3. **Given** 逻辑字段缺失或字段值为空，**When** T03/T04 解析，**Then** 仍按原契约失败或记录缺失，不把“大小写兼容”扩展为“缺字段兼容”。

---

### User Story 2 - 仓库字段访问规则一致 (Priority: P2)

作为模块维护者，我希望所有活动模块和保留支持模块在解析外部数据字段时复用同一套字段名归一化能力，避免各模块继续手写 `.lower()` 扫描或精确 `.get()`。

**Why this priority**: 当前存在 T00、T05、T08、T10 等多套重复实现，规则和冲突行为不一致，容易再次出现同类问题。

**Independent Test**: 仓库静态审计与模块回归证明外部字段解析统一走共享能力；已退休 T02 不因本次改动被重构。

**Acceptance Scenarios**:

1. **Given** GPKG、GeoJSON 或 CSV 的外部字段名使用任意大小写组合，**When** 活动模块按其契约逻辑字段读取，**Then** 得到与 canonical 字段名相同的值。
2. **Given** 模块需要原样复制输入属性，**When** 读取逻辑字段，**Then** 原始属性键名与值不被就地改写。
3. **Given** 内部审计或 handoff 字典字段拼写错误，**When** 模块按内部契约读取，**Then** 不因全局宽松查找而被静默掩盖。

---

### User Story 3 - 歧义与运行证据可审计 (Priority: P3)

作为 QA，我希望仅大小写不同的重复字段出现冲突值时显式失败，并能从错误信息、输入、参数和测试证据定位问题。

**Why this priority**: 任意选择重复字段会把数据规格冲突转化为不可追溯的拓扑错误。

**Independent Test**: 构造 `snodeid=1` 与 `snodeId=2` 的冲突记录必须失败；相同值重复字段可稳定读取且不改变原属性。

**Acceptance Scenarios**:

1. **Given** 两个字段经归一化后同名且非空值不同，**When** 建立字段查找，**Then** 抛出包含逻辑字段名和两个原始字段名的冲突错误。
2. **Given** 两个字段经归一化后同名且值相同或仅一个非空，**When** 读取该字段，**Then** 返回唯一有效值并保留原始属性。
3. **Given** 一次端到端运行，**When** 发生字段冲突，**Then** 错误不得被转换为 silent fix，且运行日志可定位输入文件与要素。

### Edge Cases

- Unicode 或非字符串字段名统一通过 `str(name).casefold()` 形成逻辑字段名。
- `None` 与非空值重复时使用非空值；两个不同非空值视为冲突。
- 候选列表可以表达模块契约已声明的历史别名，但本功能不得自动创造大小写之外的语义别名。
- 空字符串是否有效由调用模块现有字段值契约决定，字段名归一化层不改变值语义。
- 几何、CRS、拓扑修复和输出 schema 不属于字段名归一化层，不得被顺手改变。

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 提供唯一共享的字段名归一化与属性读取能力，逻辑名称采用 `str(name).casefold()`。
- **FR-002**: 共享能力 MUST 支持字段存在性、字段名解析、可选值读取、必填值读取和契约候选名列表。
- **FR-003**: 共享能力 MUST 保留输入属性的原始键和值，不得就地插入小写别名或重命名原字段。
- **FR-004**: 经归一化同名的多个字段存在不同非空值时 MUST 显式失败；不得按遍历顺序静默取值。
- **FR-005**: T03 MUST 以归一化规则读取外部 Node/Road 字段，并对必填道路 ID、端点和方向执行契约校验，禁止继续静默形成缺端点拓扑。
- **FR-006**: T04 MUST 以归一化规则执行外部 Road/Node/面要素的字段读取与必填字段校验。
- **FR-007**: Active、Active POC 以及 Support Retained 模块中的外部矢量/表格字段解析 MUST 统一复用共享能力；Retired T02 保持只读兼容，不在本轮改写超阈值文件。
- **FR-008**: 内部运行结果、审计 JSON、正式 handoff 的精确键契约 MUST 保持精确读取，除非其输入本身被对应模块契约定义为外部字段集合。
- **FR-009**: 既有模块对外入口、CLI 签名、输出文件名和 canonical 输出字段名 MUST 保持不变。
- **FR-010**: 项目级数据模型文档与受影响模块接口契约 MUST 明确“输入字段名大小写不敏感、canonical 逻辑名不变、冲突显式失败”。
- **FR-011**: 测试 MUST 覆盖共享规则、T03/T04 回归、至少一条跨模块读取链路以及静态残留审计。
- **FR-012**: 性能验证 MUST 证明字段归一化不会在每次字段读取时重复线性扫描完整属性表；单要素可复用已构建索引。

### Role Readiness

- **产品**: 仅消除字段名大小写造成的假失败，不改变任何字段值业务语义或质量判定阈值。
- **架构**: 共享能力位于项目公共层；模块只声明 logical field/candidates，外部输入与内部字典边界明确。
- **研发**: 先补失败测试，再迁移 T03/T04，随后去重其它活动模块的同类助手和外部精确访问。
- **测试**: 覆盖 canonical/camel/mixed case、缺字段、空值、重复同值、重复冲突值和原属性保留。
- **QA**: 覆盖 CRS 不变、拓扑邻接等价、几何语义不变、错误可追溯和性能基准。

### Key Entities

- **LogicalFieldName**: 模块契约中的 canonical 字段名，经 `casefold` 后用于匹配，不代表输出字段改名。
- **OriginalFieldName**: 输入文件中的实际字段名，用于保留、审计和冲突定位。
- **PropertyLookup**: 针对单个属性映射构建的可复用索引，提供解析和读取能力。
- **FieldNameConflict**: 多个 OriginalFieldName 映射到同一 LogicalFieldName 且有效值冲突的显式数据错误。

## Success Criteria

### Measurable Outcomes

- **SC-001**: T03 与 T04 对小写和 camelCase FRCSD 道路输入产生等价的解析记录和道路端点拓扑。
- **SC-002**: 用户提供的 997348/1026960 FRCSD schema 中 `snodeId/enodeId/formWay` 可通过主链必填字段校验，不再产生当前大小写错误。
- **SC-003**: 仓库审计未发现活动运行代码继续维护与共享规则重复的大小写字段扫描实现；保留项均有内部精确契约理由。
- **SC-004**: 所有新增与受影响测试通过，且未修改 CRS、几何或 topology silent-fix 规则。
- **SC-005**: 共享读取在 45 字段、5 个逻辑字段的重复访问微基准中不得慢于逐字段线性扫描；单要素构建后 100 轮字段访问不得再次迭代源 Mapping，并记录真实 1026960 数据解析耗时。
