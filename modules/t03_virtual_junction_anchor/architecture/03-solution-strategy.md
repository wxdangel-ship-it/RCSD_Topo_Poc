# 03 Solution Strategy

本文件是 T03 的架构设计 / 需求具体实现策略，说明 `../SPEC.md` 中的模块需求如何落地。稳定输入输出、状态机和入口契约见 `../INTERFACE_CONTRACT.md`；历史命名与实现构件映射在本文内保留最小说明，避免新增更深层文档路径。

## 1. 策略总览

在项目全局链路中，T03 负责补齐 T07 无法直接锚定的常规交叉 / T 型路口 1:1 关系证据。它先把“这个 SWSD 语义路口在道路面内应对应哪一组 RCSD 语义对象”解释清楚，再发布受约束的虚拟路口面和 T05 可消费 relation evidence；T03 不直接替换 Segment，也不把自身 surface 作为 T04 的几何输入。

T03 当前处理策略按正式业务主链 `Step1~Step7` 组织：

1. 建立当前 case 的代表节点、局部道路、DriveZone、RCSDRoad、RCSDNode 与冻结前置上下文。
2. 将 case 限定到当前正式支持模板：`center_junction` 或 `single_sided_t_mouth`。
3. 使用冻结合法空间作为不可反向篡改的前置约束。
4. 识别当前语义路口与 RCSD 的 `A / B / C` 关联关系，并形成 `related` 证据层。
5. 将不应进入当前路口面的 RCSD 对象分为 `foreign_mask` hard negative 或 audit-only foreign。
6. 在合法空间、方向边界、local required RC 与 hard negative mask 约束下生成最终候选几何。
7. 将结果发布为 `accepted / rejected`，并生成 formal、review-only 与 internal full-input 成果。

历史 `Association` 与 `Finalization` 不再作为方案主结构，只作为现有入口、输出文件名、代码符号和历史 closeout 的兼容命名。

## 2. 历史命名边界

| 历史标签 | 当前业务解释 | 允许出现的位置 |
|---|---|---|
| `Association` | `Step4 + Step5` 的历史联合实现阶段，承载 RCSD 关联、required / support / excluded 分类、状态与审计文件 | 现有 CLI、代码类名、输出文件名、测试、历史 closeout、兼容说明 |
| `Finalization` | `Step6 + Step7` 的历史 finalization / delivery 阶段，承载受约束几何、最终发布、review PNG 与 batch closeout | 现有代码类名、输出文件名、测试、历史 closeout、兼容说明 |

现有 `association_*`、`step7_*`、`AssociationContext`、`AssociationCaseResult`、`FinalizationContext`、`FinalizationCaseResult` 等命名是兼容资产，本轮不重命名。正式需求、架构主线和验收口径仍按 `Step1~Step7` 表达。

## 3. Step1 当前 case 受理与局部上下文

业务目的：

- 确定当前 SWSD 语义路口的代表节点、组内节点、局部道路、DriveZone、RCSDRoad 与 RCSDNode 上下文。
- 为后续 Step2-Step7 提供可追溯的 case-local world，避免后续步骤从全量数据中隐式补取对象。

输入前提：

- `nodes / roads / DriveZone / RCSDRoad / RCSDNode` 已具备可用 CRS 和必要字段。
- 代表 node 必须可定位；代表 node 缺失是结构问题，不允许 silent fallback。

输出与审计：

- case 元信息、代表节点、语义路口集合、局部道路集合和空间上下文。
- full-input 模式下，case 级 terminal record 必须能追溯 candidate discovery 与局部上下文查询。

## 4. Step2 模板归类

业务目的：

- 将当前 case 限定到 T03 正式支持的常规路口模板。
- 把 T04 负责的分歧、合流、连续复杂路口，以及环岛等非目标对象挡在 T03 外部。

正式模板：

- `center_junction`
- `single_sided_t_mouth`

对错边界：

- 对：模板不匹配时明确退出或拒绝，并记录原因。
- 错：为了提高成功率，把 div/merge、complex 128 或环岛塞进 T03。

## 5. Step3 合法活动空间冻结

业务目的：

- 冻结当前 case 的合法活动空间，作为 Step4-Step7 不可反向篡改的前置约束。
- 明确哪些道路面、分支、foreign 对象、邻近语义路口和对向空间不能进入当前路口面。

关键要求：

- `allowed_space` 必须受 DriveZone 约束。
- own-group nodes 是 must-cover 目标，但不能为了覆盖它们突破合法空间。
- `single_sided_t_mouth` 的 DriveZone 边界微偏移只允许影响组件触达判定参考，最终面仍必须完全落在 DriveZone 内。
- 当目标语义节点仅以小容差贴近 DriveZone 边界，且每个目标节点均有进入 DriveZone 的 incident road 支撑时，Step3 可扩大“候选组件触达目标”的参考容差；该规则只解决贴边目标点误判，不放宽最终 `allowed_space` 必须完全落在 DriveZone 内的硬约束。
- Step3 的冻结结果必须能被 Step4-Step7 直接消费，后续步骤不得重写 Step3 规则。
- 合法空间、负向掩膜、must-cover 与 no-silent-fallback 语义必须保持冻结，不由后续步骤回写。

输出与审计：

- `step3_status.json`
- `step3_audit.json`
- `step3_allowed_space.gpkg`
- 必要的 `target_edge_touch_enabled / reason / tolerance_m / target_drivezone_distances_m`、negative mask、selected road 和失败原因审计字段。

## 6. Step4 RCSD 关联语义识别

业务目的：

- 解释当前 SWSD 语义路口与 RCSD 语义对象之间的业务关联，而不是直接生成最终 polygon。
- 将 RCSD 对象分为 `related`、`local_required`、`support`、`excluded / foreign` 等可被 Step5-Step6 消费的语义层。

### 6.1 A / B / C 场景分类

`A / B / C` 是 Step4 的核心业务场景概念，用于说明当前 RCSD 证据对这个 SWSD 路口的支撑角色。它不是视觉等级，也不是 Step7 的最终发布状态。

| 分类 | 业务解释 | 后续消费方式 |
|---|---|---|
| `A` | 主关联成立。当前 SWSD 路口具备可解释的 RCSD 语义核心，required RCSDNode / RCSDRoad 能支撑当前路口关系。 | Step6 需要在 directional boundary 内覆盖 local required RC；Step7 accepted 后可形成 T05 成功 relation 候选。 |
| `B` | 支持性关联成立。当前 case 有 road-only、hook zone 或 support RCSDRoad 证据，但不足以证明完整 RCSD 语义核心。 | Step6 可消费 support 证据辅助构面或 seam bridge；T05 relation evidence 应表达 `rcsd_present_not_junction`，不得伪装成成功语义 relation。 |
| `C` | 关联不成立或不应消费。当前 RCSD 对象与该 SWSD 路口无有效关联，或只应作为 foreign / excluded / audit-only 证据。 | 不进入 required/support 证据；必要时进入 Step5 hard negative mask 或审计解释。 |

分类边界：

- `A` 只说明 RCSD 语义关联成立，不保证 Step6 几何一定成立，也不保证 Step7 一定 accepted。
- `B` 是保守业务分类，不等价于算法失败；它说明“有 RCSD 支撑，但不足以发布语义路口 relation”。
- `C` 不是低质量视觉结果，而是关联事实不成立或不应被当前 case 消费；即使后续 surface accepted，也只能形成无 RCSD relation 的虚拟面审计结果。

状态字段分工：

| 字段 | 业务解释 |
|---|---|
| `association_class` | 说明 RCSD 证据在当前 SWSD 路口中的角色。 |
| `association_state` | 说明 Step4 关联判断是否稳定、是否需要 review 或是否被前置条件阻断。 |
| `step7_state` | 说明虚拟路口面是否满足冻结约束并可发布。 |
| `relation_state / status_suggested` | 说明下游是否可以消费为 SWSD-RCSD 语义路口 relation。 |

其中 `association_class = C` 且 `association_state = established` 表示“已稳定判定无可消费 RCSD relation”，不是 relation 成功。

### 6.2 业务原则

- `A / B / C` 是业务关联解释，不是视觉结果等级。
- `Step4 / Step5 / Step6` 的 RCSD 口径分为三层：`related` 表示完整关联证据，`local_required` 表示 directional boundary 内 must-cover 子集，`foreign_mask` 表示 Step6 hard subtract 来源。
- `Step7 accepted` 只说明 surface 可发布；relation 成功必须由 `association_class = A`、required RCSD 语义路口证据和 relation evidence 共同确认。
- `B` 可以支撑 Step6 几何收敛，但不得写成成功语义路口 relation。
- `C` 可以解释为“无可消费 RCSD relation”，不得用 `association_state = established` 反推 relation 成功。

### 6.3 实现与审计约束

- `RCSDRoad.formway` 存在且可解析时，调头口判定优先使用 `(formway & 1024) != 0`，字段名大小写不敏感；缺字段时才使用 strict 几何 fallback。
- 无 `formway` 的 strict 几何 fallback 必须同时满足：连接两个不同 RCSD 语义路口、两端语义折叠后均为 effective degree=3、两端主干 pair 共线、两端主干轴近似平行、可信方向证明两条主干方向相反。方向不可用或不可信时只能进入 suspect 审计，不直接过滤。
- 同路径 `degree = 2` connector chain 要先保护，再执行最终调头过滤，避免短分段被误判为错误 RCSD 支撑；若 road 已满足 strict fallback，可覆盖同路径保护进入最终调头口集合；若 tentative 调头过滤后才形成 degree-2 同路径证据，最终过滤前必须回补复核。
- `related_outside_scope_rcsdroad_ids` 只能从 `required_rcsdroad_ids` 经 allowed/candidate 范围内的非语义 connector 做一跳延伸；不得从 support/group related road 外扩，不得递归多跳吞入远端 road；遇到有效 RCSD 语义路口边界、远端节点未打包 / 非 active 或 connector 不在当前 allowed/candidate 口径内时必须停止。
- 共享同一非空 `mainnodeid` 且空间紧凑的多点 RCSD 候选组必须按 group 计算 connector degree；若 group effective degree = `2`，仍按非语义 connector 处理；若 group 非 degree-2 且至少两个 incident road 已进入 related，同组 active node 进入 related，但其他同组 incident road 不得仅因 group 成立自动进入 related。
- Step4 的 required core 需要额外通过模板相关 gate：`center_junction` 需要 anchor-local、近邻成对或结构一致且偏移受限的紧凑高阶 RCSD 复合语义组；`single_sided_t_mouth` 需要 anchor-local、横向成对、代表点近处紧凑复合组或 allowed-only 紧凑复合组。
- 已落在当前 SWSD surface 内但不满足 anchor-local / 成对条件的 single-sided compact group，不得仅凭 compact 身份升格为 A 类。
- 远端下一语义路口只能作为道路延伸终点，不得把远端之后的 incident road 纳入当前 related。

输出与审计：

- RCSD 关联分类、required / support / foreign 来源、调头口审计、required core gate audit。
- `RCSDNode` 候选升格 / 降级必须写入 `required_rcsdnode_gate_audit` 与 `required_rcsdnode_gate_dropped_ids`，确保 A/B 边界可追溯。

## 7. Step5 foreign / excluded 负向约束

业务目的：

- 将 Step4 的事实解释转为 Step6 可消费的 hard negative mask 和 audit-only foreign。
- 防止当前路口面吞入相邻路口、对向道路、错误 RCSD 分支或已明确排除对象。

关键要求：

- 已判定为 `related` 的 RCSDRoad 不进入 hard negative mask。
- 当前 hard negative mask 仅由 `foreign_mask_source_rcsdroad_ids / excluded_rcsdroad -> road-like 1m mask` 进入 Step6。
- `foreign_mask` 是 Step6 的硬边界，不是 review 颜色表达。
- audit-only foreign 只能用于解释风险，不得参与几何硬裁剪。

## 8. Step6 受约束几何生成

业务目的：

- 在 Step3 合法空间、Step4 RCSD 关联、Step5 hard negative mask 和 directional boundary 内生成最终候选面。

业务原则：

- 必须在 directional boundary 内构面，不允许为满足 required RC 而突破 Step3 legal space 或 Step6 directional boundary。
- B 类 support-only case 可以加入目标节点附近 seam bridge，但 bridge 仍受 legal space、directional boundary 与 hard negative mask 约束。
- Step6 几何收敛只说明 surface 候选成立，不替代 Step4 的 RCSD relation 语义判断。

实现与审计约束：

- 对 `single_sided_t_mouth + association_class=A`，横方向口门按“竖向 RCSDRoad seed -> 横向 tracing -> terminal RCSDNode -> +5m -> stop at next directly-associated semantic junction”求解。
- Step4 强相关 RCSD 语义路口最多两个；远端下一语义路口只承担道路延伸终点角色，不进入当前 required core，也不得把该远端之后的 incident road 纳入当前 related。
- 强相关集合能覆盖横向两侧且不缩短已确认 terminal extent 时用于收敛 tracing，否则保留既有可达 endpoint tracing。
- Step4 已标记的 overflow / remote terminal node 不得被 fallback tracing 再次提升为 terminal。
- 对冻结 Step3 已应用 `two_node_t_bridge` 的 case，后续几何必须继承该中心桥接支撑，不能由横向裁剪引入中心断开或桥位空洞。

输出与审计：

- Step6 几何状态、候选 polygon、几何风险和失败原因。
- 几何 cleanup 不能静默补救拓扑或边界违反。

## 9. Step7 最终验收与发布

业务目的：

- 将 Step6 结果压缩为正式机器状态，并发布 T03 对下游可消费的 formal 成果。

正式状态：

- `accepted`
- `rejected`
- 批量运行另需区分 `runtime_failed`

正式输出：

- `virtual_intersection_polygons.gpkg`
- `nodes.gpkg`
- `nodes_anchor_update_audit.csv/json`
- `t03_swsd_rcsd_relation_evidence.csv/json`
- `intersection_match_t03.geojson`

对错边界：

- 对：review PNG 和 `V1~V5` 只作为人工复核材料。
- 错：把 `V1~V5` 反写为机器正式状态，或新增第三种 Step7 formal 状态。
- review PNG 深红 RCSDRoad 只表达强语义 `related_rcsdroad_ids / required_rcsdroad_ids`；`support_rcsdroad_ids` 保持 amber 辅助证据表达，不参与 required 延伸口径。

## 10. 实现分层

- `association_loader.py` 与 full-input shared query 层负责 `Step1 / Step2` 的输入受理、局部上下文与模板归类。
- `step3_engine.py` 与 `legal_space_*` 文件负责 `Step3` 合法空间冻结。
- `step4_association.py` 负责 `Step4` RCSD 关联语义识别。
- `step5_foreign_filter.py` 负责 `Step5` foreign / excluded 分组与审计。
- `step6_geometry.py` 负责 `Step6` 受约束几何生成。
- `step7_acceptance.py`、`finalization_outputs.py` 与 `t03_batch_closeout.py` 负责 `Step7` 发布、写盘与批量 closeout。

支撑构件按当前代码命名保留，例如 `association_outputs`、`association_batch_runner`、`finalization_outputs`；这些名称只表达实现历史，不改变正式业务步骤。

## 11. internal full-input 主链

internal full-input 不再把“先切最小 case-package 再 batch”视为默认主形态。当前主链为：

1. `candidate discovery`
2. `shared handle preload`
3. `per-case local context query`
4. direct `Step1~Step7` case execution
5. streamed / terminal state 写出
6. batch closeout

主运行脚本与监控脚本：

- `scripts/t03_run_internal_full_input_8workers.sh`
- `scripts/t03_watch_internal_full_input.sh`

历史 finalization shell wrapper 已退役，不承担模块级主命名。

## 12. 输出策略

- case 级 formal 输出保留现有文件名，包括 `association_*`、`step6_*`、`step7_final_polygon.gpkg`、`step7_*`。
- review-only 输出保留 `association_review.png`、`step7_review.png` 与 `t03_review_*` 目录。
- batch / full-input formal 输出固定包括：
  - `virtual_intersection_polygons.gpkg`
  - `nodes.gpkg`
  - `nodes_anchor_update_audit.csv`
  - `nodes_anchor_update_audit.json`
  - `t03_swsd_rcsd_relation_evidence.csv/json`
  - `intersection_match_t03.geojson`
- `_internal/<RUN_ID>/terminal_case_records/<case_id>.json` 是 authoritative terminal state。
- `t03_streamed_case_results.jsonl` 是 compact append log，不作为唯一准真值。

## 13. 性能与观测策略

- shared-layer 查询使用空间索引与缓存，不回退到全层线性扫描。
- root progress / performance 文件受 flush gate 控制，避免每 case 高频重写。
- case-level terminal record 使用 atomic write。
- perf audit 继续记录 `candidate_discovery / shared_preload / local_feature_selection / step3 / step4 / step5 / step6 / step7 / output_write / observability_write` 等阶段耗时。
- review PNG 在 production no-debug 路径默认关闭；开启 review 时仍保持现有平铺输出契约。
