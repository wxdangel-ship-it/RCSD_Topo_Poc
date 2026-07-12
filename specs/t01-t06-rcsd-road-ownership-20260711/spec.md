# T01/T06 RCSD Road 唯一归属与 Segment 替换定位升级 Spec

**Feature Branch**: `codex/t06-rcsd-ownership-20260711`
**Created**: 2026-07-11
**Status**: Draft for implementation
**Input**: 基于 SWSD 路口 1V1 锚定与 Segment 结构，为全部 RCSD Road 建立准确、可审计的归属；新增 T01 提右 Segment；保持 Step2 正式可替换输入集合可追溯，允许对基线中有明确错误证据的 Segment 少量回退；将跨 Segment 连通 Road 从 Segment 替换中拆出。

## 1. 业务定位

T06 从“Segment 替换执行模块”升级为“RCSD Road 归属、Segment 构建质量判断与替换执行承接模块”。

业务顺序固定为：

1. T01 发布普通 Segment 与提右 Segment；
2. T05 relation 提供普通 Segment 的 Pair/Junc 路口锚定；
3. T06 为原始 RCSD Road 建立归属；
4. T06 判断 Segment 构建是否完整、是否可替换；
5. Step3 执行 replacement plan，并单独处理提右与多 Segment 连通补充；
6. 输出 RCSD Road 使用率、Segment 替换率和不可替换根因。

“归属”“构建完整度”“可替换性”“最终是否进入 F-RCSD”是四个不同事实，禁止相互替代。

## 2. User Scenarios & Testing

### US1 - T01 发布独立提右 Segment（P1）

作为 T06 使用者，我希望 T01 把 SWSD 提右 Road 构造成独立 Segment，使 RCSD 制作范围更宽的提右 Road 有明确承载对象，同时不污染普通 Segment 锚定。

**Independent Test**：在 Case `1885118` 重跑 T01，所有 `formway & 128 != 0` 的 SWSD Road 都进入且只进入提右 Segment；普通 Segment 的 Step2 可替换冻结集合不减少。

**Acceptance Scenarios**：

1. Given 一组相互连通的 SWSD 提右 Road，When T01 聚合 Segment，Then 生成只包含提右 Road 的 `advance_right` Segment。
2. Given 提右 Segment，When T06 Step1/Step2 处理，Then 不要求 Pair/Junc relation，直接路由到 Step3 现有提右业务链路。
3. Given 普通与提右 Road 相邻，When 发布 Segment，Then 两类 Road 不得混入同一 Segment。

### US2 - 为全部原始 RCSD Road 建立唯一归属（P1）

作为归属审计者，我希望每条原始 RCSD Road 只落一条正式 ownership 记录，避免同一 Road 被多个 Segment 重复宣称。

**Independent Test**：对 `1885118` 的 6,435 条原始 RCSD Road 生成 6,435 条 ownership 记录，`rcsd_road_id` 唯一，且每条记录均进入明确 owner 类型或严格受控的 unresolved。

**Acceptance Scenarios**：

1. Given RCSD Road 可由一个普通或提右 Segment 解释，Then `owner_type=single_segment` 且只有一个 `owner_segment_id`。
2. Given RCSD Road 是调头口、平行路连接或二度连通桥接，且两端关联多个 Segment，Then `owner_type=multi_segment_connectivity`，只落一次，并记录 `related_segment_ids`。
3. Given RCSD Road 确认属于现实变更，Then `owner_type=reality_change` 并保留排除其它 owner 的证据。
4. Given 所有证据耗尽仍无法确定相关 Segment，Then 才允许 `owner_type=unresolved_exception`，并记录候选、尝试规则和失败原因。

### US3 - 普通 Segment 替换必须服从完整锚定与 Step2 边界（P1）

作为 F-RCSD 质量负责人，我希望普通 Segment 只有在所有 Pair/Junc 端点锚定和拓扑要求满足时才替换，不能由 group probe 覆盖锚定失败。

**Independent Test**：`1885118_1915013` 的 Junc `1898198` 为无效 relation 时保持 SWSD，不得以 path-corridor Segment replacement 进入最终 replaced relation。

**Acceptance Scenarios**：

1. Given Pair 与全部非豁免 Junc 均锚定且 Step2 replaceable，Then 可进入普通 Segment replacement plan。
2. Given Pair 成功但任一非豁免 Junc 缺失或无效，Then RCSD 可继续归属该 Segment，但 Segment 不得替换。
3. Given Segment 不在 Step2 replaceable，Then group probe 不得将其发布为 Segment replacement；如符合多 Segment connectivity，则以 connectivity action 单独处理。
4. Given Step2 基线可替换 Segment，Then本轮改动不得使其从 Step2 replaceable 集合消失。

### US4 - 允许附属侧路缺失的受控混合替换（P2）

作为业务使用者，我希望 RCSD 主干完整时能够替换主干，但仅在附属侧路缺失的情况下保留 SWSD 侧路。

**Independent Test**：构造主干完整、附属侧路缺失的 Segment，验证主干 RCSD 进入 F-RCSD、缺失侧路 SWSD 保留，并输出 `replaced+retained_swsd`；主干缺失或不连通时不得走该路径。

### US5 - 多 Segment 连通归属与指标分离（P1）

作为指标维护者，我希望可挂接的调头口、平行路连接或二度连通桥接能够进入 F-RCSD，但不虚增 Segment 替换率。

**Independent Test**：跨两个 Segment 的线性二度连通组只生成一个 connectivity group 和一组 Road ownership；Road 进入 F-RCSD 并计入 RCSD Road 替换率，两个 Segment 的替换状态不因该组改变。

**Acceptance Scenarios**：

1. Given 连通组两端均可挂接且不触达受保护 Pair/Junc，Then `connectivity_status=attachable`，允许执行 `include_connectivity`。
2. Given 相关 Segment 可确定但无法安全挂接，Then 保留 `multi_segment_connectivity` 归属但 `replacement_status=not_replaced`。
3. Given 连相关 Segment 集合都不能确定，Then 进入 `unresolved_exception`，不得进入 connectivity group。

### US6 - 可追溯根因与不回退回归（P1）

作为 QA，我希望六 Case 的 Step2 输入基线可复算，Segment 替换结果仅在有显式错误证据时允许少量回退，并对当前 67 个 Step2 外成功替换 Segment逐个给出新业务处置与根因。

**Independent Test**：先在 `1885118` 生成 before/after 差分和 28 个对象根因表，通过后再运行六 Case，验证冻结集合、RCSD Road 归属、Segment 指标和 topology audit。

## 3. Edge Cases

- RCSD Road 同时落入多个 Segment buffer：buffer 只产生候选，不得直接形成多个 owner。
- 同一 RCSD Road 因 copy-on-write 切分生成多个 final Road：ownership 仍以原始 `rcsd_road_id` 唯一，记录 `final_road_ids`。
- Pair relation 缺失、单侧成功、同归一或图不可消费：不得强制替换；ownership 允许继续收敛。
- Junc relation 缺失或无效：普通 Segment 不替换。
- 提右 Segment：不参与 Pair/Junc 锚定，也不进入普通 Segment 分母。
- 调头口/平行连接：允许 multi-segment connectivity，不得复制到各 Segment owner。
- 非线性、开放端点、触达受保护锚点或候选 Segment 歧义的连通组：不执行，保留审计。
- reality change：不能作为无 owner 的默认兜底。
- unresolved：不能只记录“几何不确定”，必须列出证据耗尽链路。
- summary 与最终文件行数不一致：运行应失败或显式标记审计不一致。

## 4. Functional Requirements

- **FR-001**: T01 MUST 新增 `advance_right` Segment，且其中全部 Road 必须满足正式提右属性规则；普通 Road 不得混入。
- **FR-002**: 提右 Segment MUST 不参与普通 Segment 的 Pair/Junc 锚定，`pair_nodes/junc_nodes` 为空或使用契约化的非锚定表达。
- **FR-003**: T01 MUST 为提右 Segment 输出稳定 id、Road 列表、构建来源和审计统计，不得新增 CLI 或正式入口。
- **FR-004**: T06 MUST 在 Step1/Step2 前识别 Segment 类型；普通 Segment 继续走 Step1/Step2，提右 Segment 路由到 Step3 现有提右逻辑。
- **FR-005**: T06 MUST 输出覆盖全部原始 RCSD Road 的 ownership ledger，每个 `rcsd_road_id` 恰好一行。
- **FR-006**: ownership ledger 的 `owner_type` MUST 取 `single_segment / multi_segment_connectivity / reality_change / unresolved_exception` 之一。
- **FR-007**: `single_segment` MUST 只有一个 `owner_segment_id`；候选 Segment 可另行记录，但不得形成重复正式 owner。
- **FR-008**: `multi_segment_connectivity` MUST 只有一个 `connectivity_group_id`，并通过 `related_segment_ids` 记录多个 Segment。
- **FR-009**: 普通 Segment 只有在全部 Pair nodes 和非豁免 Junc nodes relation 可消费、required topology 成立且 Step2 replaceable 时，才可计为 Segment replaced。
- **FR-010**: Pair 成功但 Junc 缺失/无效时，T06 MUST 保留 ownership 诊断，但 MUST NOT 执行普通 Segment replacement。
- **FR-011**: Step2 外 rejected Segment MUST NOT 仅因 `group_probe_status=passed` 被计为 Segment replaced。
- **FR-012**: path-corridor group probe 的道路如满足独立 multi-segment connectivity 规则，可发布 `include_connectivity` action；该 action不得改变成员 Segment replacement 状态。
- **FR-013**: 可挂接 multi-segment connectivity Road MUST 计入 RCSD Road 替换数量与里程，MUST NOT 计入 Segment 替换数量或分母。
- **FR-014**: 相关 Segment 已知但无法挂接的 connectivity group MUST 保留归属与失败原因，不得进入 F-RCSD。
- **FR-015**: `unresolved_exception` MUST 记录候选 Segment、已尝试规则、失败证据、人工复核标记和排除 reality change/connectivity 的理由。
- **FR-016**: `reality_change` MUST 记录不在任何 SWSD Segment/提右 Segment/连通组范围内的证据，不得由零候选自动生成。
- **FR-017**: 2b 混合替换 MUST 只允许主干完整且仅附属侧路缺失；主干断头、方向缺失、拓扑不连通或端点无法闭合时不得替换。
- **FR-018**: 本轮 MUST 冻结六 Case 的 2,484 个 Step2 可替换 Segment id；实现后普通 Segment Step2 集合不得减少。
- **FR-019**: 本轮 MUST 对六 Case 当前 67 个 Step2 外成功替换 Segment逐个输出根因、新 owner 类型、是否仍进入 F-RCSD以及是否计 Segment 指标。
- **FR-020**: 最终 RCSD Road 使用事实与未替换事实 MUST 对全部原始 RCSD Road 无遗漏、无交叉。
- **FR-021**: 最终 summary MUST 与 GPKG/CSV 实际行数一致；差异必须作为 QA failure 暴露。
- **FR-022**: 所有 GIS 输出 MUST 保持可定位 CRS；不得 silent fix 拓扑或无效几何。
- **FR-023**: ownership 决策 MUST 记录输入路径、参数、证据类型、候选、owner、置信度、输出和运行环境。
- **FR-024**: 性能验证 MUST 分别记录 `1885118` 与六 Case 的 ownership、连通组、归因和 Step3 耗时；优化不得改变归属和指标语义。
- **FR-025**: 正式 topology 指标 MUST 使用 `final_frcsd_topology_fail_count`，只统计最终 F-RCSD 的 `segment_transition / independent_attachment` hard fail；兼容 `topology_connectivity_fail_count` 仅表示审计 fail 行数。
- **FR-026**: 正式 topology fail MUST 使用逐层稳定业务主键去重；同 Segment 多条 SWSD Road、同提右 Road 不同端点和无 Segment relation 的不同提右 Road不得互相折叠。
- **FR-027**: `segment_relation_failed`、coverage、source consistency 和仅映射证据缺失 MUST NOT 进入 `final_frcsd_topology_fail_count`，但原审计行必须保留供其它指标消费。
- **FR-028**: 提右来源选择 MUST 只以提右两端相邻的普通 Segment 是否替换为依据；`segment_type=advance_right` 的提右 Segment 自身不得作为 retained side 干扰 mixed 判定。两侧普通 Segment 均 replaced 且存在几何一致的 RCSD 提右时 MUST 使用 RCSD 提右。
- **FR-029**: 一侧普通 Segment replaced、另一侧 retained/failed 时 MUST 保留 SWSD 提右，并在 replaced 侧按该侧已选 RCSD Road执行唯一、方向与几何一致的 mixed attachment；T01 提右 Segment 的独立 `segmentid` 不得把该挂接误收紧为 legacy 1m direct-context gate。
- **FR-030**: 显式 `split/reuse attachment` 生成的 SWSD-RCSD mainnode 关系 MUST 高于 retained Segment identity/peer mainnode 同步优先级，后续 relation refresh 不得覆盖。
- **FR-031**: 正式发布前 MUST 清除 T06 引入的 `segment_transition` fail；无法安全闭合 replaced/retained 共同路口时 MUST 受控回退相关 replaced plan，不得仅记录 manual review 后继续发布。
- **FR-032**: `final_rcsd_advance_right_leaf_endpoint_has_unselected_native_rcsd_neighbor` 属于已接受的 RCSD 提右边界审计，MUST 保留明细但 MUST NOT 计入 `final_frcsd_topology_fail_count`。

## 5. Key Entities

- **SWSD Segment**：T01 输出的业务道路单元，类型为 `normal` 或 `advance_right`。
- **RCSD Road Ownership**：一条原始 RCSD Road 的唯一归属事实。
- **Multi-Segment Connectivity Group**：服务多个 Segment 的调头、平行连接或二度连通 Road 组。
- **Segment Construction Audit**：普通 Segment 的锚定、主干完整度、附属侧路缺失和 RCSD 质量结论。
- **Replacement Action**：`replace_segment / replace_main_retain_side / include_connectivity / hold`。
- **Reality Change**：经证据确认不属于任何现有 SWSD Segment 的 RCSD Road。
- **Unresolved Exception**：证据耗尽后仍不能可靠确定 owner 的极少量对象。

## 6. Success Criteria

- **SC-001**: 六 Case 原始 RCSD Road ownership 覆盖率为 `100%`，同一 `rcsd_road_id` 重复正式 owner 数为 `0`。
- **SC-002**: `1885118` 的 979 个及六 Case 合计 2,484 个 Step2 正式可替换输入必须完整读取并可追溯；最终 Segment 替换数允许低于旧基线，但每个回退必须有违反 1V1、完整锚定、严格 2b carrier 或 topology hard gate 的显式证据。`1885118` 冻结基线 `937` 不是无条件下限。
- **SC-003**: Junc relation 缺失/无效的 Step2 外 Segment 不再计为 Segment replaced；`1885118_1915013` 必须成为标准回归。
- **SC-004**: 六 Case 当前 67 个 Step2 外成功替换对象全部具有逐项根因与新业务处置，不得留空。
- **SC-005**: multi-segment connectivity Road 只落一个 group owner；可挂接 Road进入 RCSD Road 替换指标但不改变 Segment 替换指标。
- **SC-006**: 原始 RCSD Road 在“最终使用”和“未替换”集合之间遗漏为 `0`、交叉为 `0`。
- **SC-007**: `unresolved_exception` 每条都有完整证据耗尽链路；其数量在 `1885118` 每轮审计中单调不增加，并在六 Case closeout 前形成逐项人工/规则处置清单。
- **SC-008**: 六 Case CRS 一致、无新增空/无效几何、无 silent topology fix；topology hard fail 不得因 ownership 变更增加。
- **SC-009**: 先完成 `1885118` 单元/集成/Case 回归，再执行其余五 Case；顺序不得倒置。
- **SC-010**: 六 Case 的 `final_frcsd_topology_fail_count` 可从正式 GPKG/CSV 按 `final_topology_object_key` 唯一回算，并与 summary 完全一致；同轮 topology-safe rollback 只消费该正式 fail 集合。
- **SC-011**: 当前六 Case 已确认的 31 个 T06 必修对象清零：9 个错误 SWSD 提右来源、10 个 mixed attachment 失败、10 个 replaced/retained Segment transition 失败和 2 个 split mainnode 覆盖；14 个已接受 RCSD 边界叶子只保留审计，1 个输入 SWSD 原生叶子单列 inherited input。

## 7. Non-Goals

- 不回写或静默修复 T05 relation 主表。
- 不把 RCSD `formway=128` 直接等同于 SWSD 提右 Segment owner。
- 不通过扩大 buffer、最近距离或固定优先级强行消除 ownership 冲突。
- 不新增 repo CLI、`scripts/`、`tools/`、Makefile 入口。
- 不在本轮修改 T09 restriction 业务规则；仅保持其 relation 消费兼容。
- 不刷新正式 baseline 指针，直到六 Case 完整回归通过并得到明确授权。
