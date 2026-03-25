# Feature Specification: T02 虚拟路口锚定统一全量入口 POC

**Feature Branch**: `codex/t02-virtual-anchor-poc-spec`  
**Created**: 2026-03-25  
**Status**: Draft  
**Input**: User description: "我们现在虚拟路口锚定有三种处理入口：1. 测试用例入口：每个测试用例拥有完整的数据，作为基线用例不回退 2. 完整数据入口+指定路口：正式方案的特例，用于单点验证某个路口 3. 完整数据入口：正式方案，识别mainnode有道路面资料，但未被锚定的路口，进行虚拟路口锚定 2、3统一成一个入口，通过命令参数完成不同的业务诉求 2、3需要进行性能优化，并行化处理，提高性能 2、3产出的虚拟路口输出为一个路口面图层，Render成果也放在一个目录下便于查看。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 统一全量入口支持“指定路口”和“自动识别”两种模式 (Priority: P1)

作为 T02 操作者，我希望在“完整数据入口”里只用一个命令入口，就能通过参数同时满足两种业务诉求：一是指定某个 `mainnodeid` 做单点验证，二是自动识别所有“有道路面资料但未被锚定”的候选路口并批量处理。

**Why this priority**: 这是用户刚刚明确冻结的核心入口模型。如果 2、3 仍然拆成两个入口，后续正式化会继续出现口径分裂。

**Independent Test**: 对同一套全量输入，分别运行“带 `--mainnodeid`”和“不带 `--mainnodeid`”两种模式。前者必须只处理指定路口，后者必须自动发现候选并处理前 N 个。

**Acceptance Scenarios**:

1. **Given** 全量输入图层可读且操作者显式传入 `mainnodeid`，**When** 运行统一全量入口，**Then** 系统必须只处理该指定路口，不再自动扩展到其它候选。
2. **Given** 全量输入图层可读且未传入 `mainnodeid`，**When** 运行统一全量入口，**Then** 系统必须自动发现符合条件的路口候选并开始批量处理。

---

### User Story 2 - 通过参数控制最大处理量并支持并行化 (Priority: P2)

作为 T02 操作者，我希望在全量入口的自动识别模式下，同时控制“本轮最多处理多少个候选路口”和“并行处理多少个路口”，从而让一次运行既可控又更快。

**Why this priority**: 用户已经明确要求 2、3 的正式入口做性能优化和并行化。没有这一层，全量入口即使统一了也不具备实际可用性。

**Independent Test**: 给定同一套全量输入，分别运行 `max_cases=0`、`max_cases=3`、`workers=1`、`workers=4` 等组合。系统必须稳定输出一致的候选集合和结果集合，并明确记录未处理原因。

**Acceptance Scenarios**:

1. **Given** 自动发现出的候选路口数大于 `max_cases`，**When** 运行统一全量入口，**Then** 系统只处理前 `max_cases` 个稳定排序后的候选，并明确记录其余候选是因超过上限而未处理。
2. **Given** 选中的候选数大于 1 且 `workers > 1`，**When** 运行统一全量入口，**Then** 系统必须允许并行处理多个候选，同时保持最终 summary 和统一输出图层的顺序与内容可复现。

---

### User Story 3 - 统一输出一个路口面图层和一个 Render 目录 (Priority: P3)

作为复核人员，我希望 2、3 这两种全量入口模式最终都落成统一的输出形态：一个汇总后的虚拟路口面图层、一个统一的 Render 目录，以及一份能解释候选筛选和处理结果的 summary。

**Why this priority**: 用户已经明确要求 2、3 的产出统一成“一个路口面图层 + 一个 Render 目录”。如果仍保留零散输出，就不满足这轮业务要求。

**Independent Test**: 给定一套全量输入，分别跑指定路口模式和自动识别模式。两者都必须在批次根目录写出统一的 `virtual_intersection_polygons.gpkg` 和 `_rendered_maps/`，并且不要求人工逐个拼接。

**Acceptance Scenarios**:

1. **Given** 统一全量入口已经处理完本轮所有选中的路口，**When** 运行结束，**Then** 批次根目录必须产出一个统一的虚拟路口面图层，收集所有成功生成的路口面。
2. **Given** `debug` 或 render 输出已开启，**When** 运行结束，**Then** 所有 render 结果必须落在同一个批次目录 `_rendered_maps/` 下，便于集中查看。

---

### Edge Cases

- 当测试用例入口作为回归基线时，新的统一全量入口改造如何保证不让现有 baseline case 回退？
- 当 `nodes` 中缺失 `has_evd / is_anchor / kind_2 / grade_2` 任一必需字段时，统一全量入口如何显式失败？
- 当某个 GeoPackage 有多个 layer 且无法自动唯一识别时，是否必须要求显式传 layer 参数？
- 当指定路口模式传入的 `mainnodeid` 不存在、或不满足候选资格时，系统应返回什么状态？
- 当候选总数小于 `max_cases` 时，系统如何保证“全量处理”而不是错误截断？
- 当 `max_cases` 为负数、非整数或无法解析时，入口如何拒绝？
- 当 `workers <= 0`、非整数或大于候选总数时，入口如何校验或归一化？
- 当代表 node 缺失、`mainnodeid` 组不完整、或 `nodes` 中存在无效 group 时，候选盘点如何记录排除原因？
- 当全量输入的 RCSD 图层可读但局部 patch 中 RCSD 命中数为 0 时，批量 summary 如何区分“本地确实无 RCSD”与“图层读取配置错误”？

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须保留现有测试用例入口作为基线回归入口；每个测试用例拥有完整数据的处理方式不得因本轮统一全量入口改造而回退。
- **FR-002**: 系统必须将“完整数据入口 + 指定路口”和“完整数据入口 + 自动识别候选”统一为一个正式入口，并通过命令参数区分业务模式。
- **FR-003**: 当显式传入 `mainnodeid` 时，统一全量入口必须进入“指定路口验证模式”，且只处理该指定路口。
- **FR-004**: 当未传入 `mainnodeid` 时，统一全量入口必须进入“自动识别模式”，从全量输入中自动发现需要进行虚拟路口锚定的候选。
- **FR-005**: 当前版本的默认候选判定规则必须冻结为：代表 node 满足 `has_evd = yes`、`is_anchor = no`、`kind_2 in {4, 2048}`，且能够解析出合法 `mainnodeid` 组。
- **FR-006**: 系统必须对不进入候选集合的路口保留排除原因，至少区分：`has_evd_not_yes`、`is_anchor_not_no`、`kind_2_out_of_scope`、`representative_missing_or_invalid_group`。
- **FR-007**: 系统必须支持参数化的最大处理量控制；本轮基线将“最大处理的数据量”明确解释为“本轮最多处理的候选路口数”，参数名称应清晰表达这一语义，例如 `max_cases` 或等价名称。
- **FR-008**: 当自动识别出的候选数大于最大处理量时，系统必须采用稳定、可复现的排序规则选出前 N 个执行，并把剩余候选记录为“因超过上限未处理”。
- **FR-009**: 稳定排序规则必须在文档和实现中明确；当前默认排序应采用标准化后的 `mainnodeid` 升序，除非后续变更另行冻结。
- **FR-010**: 统一全量入口必须支持并行化处理参数，例如 `workers` 或等价名称；当选中的候选数大于 1 且 `workers > 1` 时，系统必须能够并行执行多个路口。
- **FR-011**: 并行化不得改变结果语义；同一输入在 `workers=1` 与 `workers>1` 下，候选集合、每个 `mainnodeid` 的状态以及统一汇总输出必须保持一致，允许只有性能不同。
- **FR-012**: 当进入自动识别模式时，统一全量入口必须复用现有单 `mainnodeid` POC 作为 case worker，为每个选中的候选生成与单 case 相同的正式输出集合。
- **FR-013**: 当进入指定路口验证模式时，统一全量入口也必须沿用同一套输出契约；只是统一汇总图层中只包含该一个路口面的结果。
- **FR-014**: 统一全量入口运行目录必须冻结为 `<out_root>/<run_id>`，批次 render 统一写在 `<out_root>/<run_id>/_rendered_maps/`。
- **FR-015**: 统一全量入口的批次根目录必须额外输出一个统一汇总的虚拟路口面文件，例如 `virtual_intersection_polygons.gpkg`；该文件收集本轮所有成功生成的虚拟路口面，每个 feature 至少带 `mainnodeid`、`status` 和结果来源路径或等价可追溯字段。
- **FR-016**: 统一全量入口必须输出批量级 summary、perf、progress、log 和候选盘点文件，并在 summary 中同时记录：
  - 处理模式（指定路口 / 自动识别）
  - 发现的候选总数
  - 实际处理数
  - 因超过上限未处理数
  - 因资格不满足被排除数
  - `workers`
  - 每个 `mainnodeid` 的处理状态与路径
- **FR-017**: 统一全量入口必须在运行前输出全量图层的 preflight 信息，至少包括：输入路径、解析到的 layer 名、feature count、CRS 和 bounds。
- **FR-018**: 统一全量入口不得再通过硬编码 `EPSG:3857` override 读取全量 GPKG；若输入源自 GeoPackage，应优先使用数据内置 CRS，只有显式传参时才允许 override。
- **FR-019**: 当 GeoPackage 存在多个 layer 且无法自动唯一识别时，系统必须明确失败并要求显式 layer 参数，而不是默认读错层或 silent 读空。
- **FR-020**: 统一全量入口必须支持将 `review_mode`、`debug`、`debug_render_root` 透传给单 case worker，但其语义不得超出现有单 case POC 契约。
- **FR-021**: 统一全量入口必须显式声明：它仍然是“虚拟路口锚定受控实验 POC 的统一全量运行形态”，不是正式全量产线方案，也不重算 stage1 / stage2 主链。
- **FR-022**: 当前版本不得引入“按 byte、面积、几何复杂度”控制最大处理量的第二套语义；若未来需要这些语义，必须另起变更冻结，不得在本轮混入。

### Key Entities *(include if feature involves data)*

- **VirtualAnchorFullInputRequest**: 一次统一全量入口运行使用的输入集合，包含 `nodes / roads / DriveZone / RCSDRoad / RCSDNode` 路径、layer、CRS 解析结果和运行参数，例如 `mainnodeid / max_cases / workers / review_mode`。
- **VirtualAnchorCandidate**: 从全量 `nodes` 中发现的候选路口对象，至少包含 `mainnodeid`、代表 node 属性、资格判定结果、选中/未选中状态和原因。
- **VirtualAnchorRunSelection**: 本轮真正进入处理的路口集合，既覆盖指定路口模式下的单点选择，也覆盖自动识别模式下的 top-N 结果，并记录排序结果、上限截断信息和 case 输出目录映射。
- **VirtualAnchorBatchSummary**: 统一全量入口的运行摘要，记录输入 preflight、处理模式、候选盘点、实际执行结果、风险计数和性能摘要。
- **VirtualAnchorPolygonCollection**: 批处理根目录下统一汇总的虚拟路口面集合，承载所有已成功产出的单 case polygon，并保留 `mainnodeid / status / source_case_dir` 等追溯字段。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 现有测试用例入口对应的基线 case 在本变更完成后不得出现回退；既有 baseline case 的结果和审计口径必须保持可复现。
- **SC-002**: 操作者能够使用同一个完整数据入口，通过是否传入 `mainnodeid` 参数，在“指定路口验证模式”和“自动识别模式”之间切换，而不需要换命令入口。
- **SC-003**: 当配置了 `max_cases = N` 且自动识别出的候选数大于 N 时，系统处理的路口数必须精确等于 N，并且剩余候选必须 100% 在 summary 中被标注为“超过上限未处理”。
- **SC-004**: 同一套输入在 `workers=1` 和 `workers>1` 下，最终选中的 `mainnodeid` 集合和每个路口的状态必须一致；不得因并行化导致结果漂移。
- **SC-005**: 2、3 两种全量入口模式最终都必须在批次根目录产出一个统一的虚拟路口面汇总文件和一个统一的 Render 目录，无需逐个进入 `cases/<mainnodeid>/` 目录拼接。
- **SC-006**: 统一全量入口的 preflight 必须能够在运行开始前输出所有输入图层的 layer / CRS / feature count；不得再出现“RCSD 图层被静默读成 0 且无解释”的情况。
