# T04 RCSD Alignment and Surface Rules Spec

## 1. Scope

本 SpecKit 任务覆盖 T04 `t04_divmerge_virtual_polygon` 中 RCSD/SWSD 语义路口对齐、负向掩膜、六类构面场景、复杂路口 unit/case 两级对齐，以及对应的回归门禁。

本任务不直接进入编码；正式编码必须在本 spec、plan、tasks 和 gap audit 准备完成后再进入 implement 阶段。

## 2. Source Requirement Baseline

本任务以模块源事实为准，尤其是：

- `modules/t04_divmerge_virtual_polygon/INTERFACE_CONTRACT.md`
- `modules/t04_divmerge_virtual_polygon/architecture/04-solution-strategy.md`
- `modules/t04_divmerge_virtual_polygon/architecture/10-quality-requirements.md`
- `modules/t04_divmerge_virtual_polygon/architecture/12-glossary.md`

`specs/*` 是变更工件，不替代模块源事实。

`RCSD_Topo_Poc_T04_REQUIREMENT.md` 不作为更高优先级需求输入。Anchor_2 当前正式 case 清单为 `E:\TestData\POC_Data\T02\Anchor_2` 下 39 个 case；WSL 路径为 `/mnt/e/TestData/POC_Data/T02/Anchor_2`。

## 3. Business Rules

### 3.1 Semantic Junction Definition

RCSD 语义路口与 SWSD 语义路口具有相同的语义基础：

- 具有 3 条及以上道路进入或退出路口，称为语义路口。
- `mainnodeid == 0` 表示该语义路口只有 1 个节点；`mainnodeid != 0` 表示该语义路口由多个节点组成。
- 两个语义路口之间的道路视为一条道路。
- `mainnodeid` 只是组织方式，不是语义路口是否存在的充分条件；语义口径以 3 条及以上道路进入或退出为准。

### 3.2 RCSD Alignment Types

Step4 可以保留多个候选用于审计，但进入 Step5 前必须输出唯一 RCSD 对齐结果：

- `rcsd_semantic_junction`：当前 unit 或当前复杂路口整体找到唯一完整对应的 RCSD 语义路口。
- `rcsd_junction_partial_alignment`：RCSD 能召回路口级对象，但相比 SWSD 路口缺失部分进入/退出道路；剩余进入/退出道路的角度趋势和方向角色仍与当前 SWSD 路口一致。该对象可以作为路口级 section reference，但不得发布为完整 RCSD 语义路口。
- `rcsdroad_only_alignment`：RCSD 不能召回路口级对象，仅能召回可对齐 RCSDRoad 或两个 RCSD 语义路口间道路；它只可作为局部正向生长/fallback 支撑，不参与路口级截面边界构建。
- `no_rcsd_alignment`：当前 unit 或路口没有可用 RCSD 正向对齐对象。
- `ambiguous_rcsd_alignment`：存在多个可作为当前 unit / case 正向 RCSD 对齐对象的候选且无法唯一消歧；不得静默降级为 no RCSD，必须阻断正常构面并进入审计。若只是处理窗口内存在多个与当前对象无关的 RCSD 语义对象，则它们属于负向掩膜上下文，不构成该状态。

兼容字段 `rcsd_match_type` 可以继续存在，但不得替代 `rcsd_alignment_type` 做六场景截面、发布、负向掩膜、Step5/6 业务判定。

### 3.3 Positive Recall and Negative Mask

RCSD 正向召回、无 RCSD 语义路口、无 RCSD 的业务定义：

- RCSD 路口正向召回：当前 unit 或当前复杂路口找到唯一对应的 RCSD 语义路口。与该唯一 RCSD 语义路口无关的 RCSDNode/RCSDRoad 是负向掩膜输入。
- 无 RCSD 语义路口：仍可能有唯一 RCSD 对齐对象，包括 partial junction 或 road-only alignment。与该唯一对齐对象无关的 RCSDNode/RCSDRoad 是负向掩膜输入。
- 无 RCSD：所有 RCSDNode/RCSDRoad 都是负向掩膜输入。
- 与当前输入 SWSD 语义路口无关的 SWSD nodes/roads 也必须进入负向掩膜。
- 导流带本体、导流带 void/interior、不可通行区、terminal cut、forbidden domain 都属于负向约束来源。

负向掩膜必须可审计：输出应能区分 unrelated SWSD nodes/roads、unrelated RCSDNode/RCSDRoad、导流带、forbidden/cut 等来源。

### 3.4 Normal Surface Generation

六类场景共享同一底层构面逻辑：

- 单个 unit 的路口面以两个截面边界为终止，在两个边界间铺满合法道路面。
- 构面严禁侵入负向掩膜区域。
- 负向掩膜是正向掩膜不可跨越的区域；实现上可以在生长阶段抑制，也可以在后处理裁剪，但最终面必须通过截面关系、allowed growth、forbidden/terminal cut、分通道 negative mask 后验检查。不得为了追求单连通而弱化负向掩膜；也不得用 `barrier_separated_case_surface_ok` 泛化放行普通 MultiPolygon。
- 负向掩膜只允许通过对象身份排除唯一正向对象：正向 SWSD roads、正向 RCSDRoad / RCSDNode、唯一 road-only alignment 等对象不进入 unrelated 集合；不得用正向 corridor、allowed growth、case bridge 或其它几何生长域对 unrelated 掩膜做差集。若原始 unrelated 掩膜切断 allowed growth，结果必须在掩膜处截止，必要时 rejected / exception audit。
- 为避免路口面沿道路无限增长，整体控制在 RCSD/SWSD 相关道路约 20m 范围外；两侧不对称时可取两侧较远边界作为 20m 控制范围。
- 在两个截面边界内的正向 RCSDRoad 和 SWSD roads 共同参与正向掩膜生长，生长范围约 20m，最终取并集。
- Step6 不得用 relief 静默放宽 Step5 的 allowed/forbidden/terminal/lateral 硬边界；如确需改变边界，应回到 Step5 生成可审计约束。

复杂路口不是独立场景。复杂路口由多个 unit 组成，每个 unit 先按自身场景构面；随后对相邻 unit 间缝隙，沿两组 unit 的临近截面边界使用同一正向道路面生长、约 `20m` 横向控制和负向掩膜规则补面，最终应形成唯一联通的 case-level 路口面。只有当生效负向掩膜在 unit 内部或相邻 unit 间真实阻断，且 inter-unit 补面也无法在不侵入负向掩膜的前提下连通时，才允许把多组件作为 rejected / exception audit；该状态不得作为 accepted 放行条件。复杂路口必须同时提供 unit-level 和 case-level RCSD/SWSD 对齐审计。

## 4. Six Surface Scenarios

### 4.1 有主证据 + 有 RCSD 语义路口

条件：有主证据，`rcsd_alignment_type = rcsd_semantic_junction`。

规则：

- Reference Point 由主证据确定。
- RCSD 语义路口作为另一个路口级截面参考对象。
- 两个终止截面由 `Reference Point + RCSD 语义路口` 共同确定。
- SWSD 语义路口不参与截面边界构建，但参与正向 roads 解释、负向掩膜和审计。

### 4.2 有主证据 + 无完整 RCSD 语义路口但有 RCSD 对齐对象

条件：有主证据，`rcsd_alignment_type` 为 `rcsd_junction_partial_alignment` 或 `rcsdroad_only_alignment`。

规则：

- 若 `rcsd_junction_partial_alignment`：`Reference Point + RCSD partial junction` 共同确定两个终止截面；partial junction 可作为路口级 section reference，但不得发布为完整 RCSD 语义路口。
- 若 `rcsdroad_only_alignment`：两个终止截面由 `Reference Point` 自身前后 20m 构成；RCSDRoad 只可作为局部正向生长/fallback 支撑，不参与截面边界构建。
- SWSD 语义路口不参与截面边界构建。

### 4.3 有主证据 + 无 RCSD

条件：有主证据，`rcsd_alignment_type = no_rcsd_alignment`。

规则：

- 两个终止截面由 `Reference Point` 自身前后 20m 构成。
- 所有 RCSDNode/RCSDRoad 均为负向掩膜输入。
- SWSD 语义路口不参与截面边界构建。

### 4.4 无主证据 + 有 RCSD 语义路口

条件：无主证据，`rcsd_alignment_type = rcsd_semantic_junction`。

规则：

- 不得从 RCSD 反推出虚拟 Reference Point。
- 两个终止截面由 RCSD 语义路口自身前后 20m 构成。
- SWSD 语义路口不参与截面边界构建。

### 4.5 无主证据 + 无完整 RCSD 语义路口但有 RCSD 对齐对象

条件：无主证据，`rcsd_alignment_type` 为 `rcsd_junction_partial_alignment` 或 `rcsdroad_only_alignment`。

规则：

- 若 `rcsd_junction_partial_alignment`：两个终止截面由 RCSD partial junction 自身前后 20m 构成；SWSD 语义路口不参与截面边界构建。
- 若 `rcsdroad_only_alignment`：两个终止截面由 SWSD 自身前后 20m 构成；RCSDRoad 只可作为局部正向生长/fallback 支撑。

### 4.6 无主证据 + 无 RCSD

条件：无主证据，`rcsd_alignment_type = no_rcsd_alignment`，且存在 SWSD 语义路口。

规则：

- 两个终止截面由 SWSD 自身前后 20m 构成。
- 所有 RCSDNode/RCSDRoad 均为负向掩膜输入。
- 不得构造虚拟 Reference Point。

### 4.7 Defensive Fallback

`no_surface_reference` 只允许作为防御性异常兜底，表示合法 section reference 未能物化，或上游输入不满足 T04 case 基本语义前提。正常 Anchor_2 case 不应因为“无主证据 + 无完整 RCSD 语义路口”落入 `no_surface_reference`。

## 5. Acceptance Criteria

- Step4 输出并持久化唯一 `rcsd_alignment_type`，覆盖 Step4 JSON、candidate audit、review index、summary、Step5 输入。
- Step5/6 不重新选择 RCSD 候选，只消费 Step4 的唯一对齐对象和候选审计结果。
- `ambiguous_rcsd_alignment` 阻断 accepted，并写入可定位候选冲突的审计信息。
- 六类场景的截面边界来源按本 spec 精确区分 partial junction 和 road-only fallback。
- 负向掩膜可审计区分 SWSD/RCSD/divstrip/forbidden/cut 来源，并在 Step6 后验复核不侵入。
- complex/multi case 输出 unit-level 和 case-level 对齐审计，证明不跨多个无关 RCSD 语义对象混聚。
- complex/multi case 必须在 unit surface 合并后执行相邻 unit 的 inter-unit section bridge；若没有真实负向掩膜阻断，最终 `final_case_polygon` 必须是唯一联通面。
- `barrier_separated_case_surface_ok` 只能作为真实负向掩膜阻断的审计标记；只要 `final_case_polygon` 不是唯一联通面，Step7 就不得 accepted。
- 原 30-case baseline、新增 6-case gate、重点问题 case 与统一 39-case gate 不漂移。
- 所有发布 GPKG/GeoJSON 均断言 CRS=`EPSG:3857`、geometry valid、非空、summary/audit/feature count 一致。
- 视觉审计工件可追溯，至少包含可供人工检查的 final review PNG 和索引；最终目视图必须标注 `surface_scenario_type`、唯一正向 RCSD 对齐对象的粗红 RCSDRoad，以及构成截面边界的参考对象。`no_rcsd_alignment` 不绘制粗红 RCSDRoad，其无 RCSD 正向召回语义由场景标注表达。
- 性能审计保留 39-case/full-input 的耗时记录，并设定准出阈值。

## 6. Non-Goals

- 不新增 repo 官方 CLI 或改变官方入口。
- 不改变 T04 surface 主产物命名。
- 不把 RCSD/SWSD 语义路口伪造成主证据或 Reference Point。
- 不以追求 accepted 数量为目标改写正确 rejected case。
- 不根据局部样本反推上游字段语义并固化为强规则。
