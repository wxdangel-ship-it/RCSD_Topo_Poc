# T06 Root5 Step3 Top20 替换口径修正规格

## 1. 目标

本轮修正 T06 Step2/Step3 在 Top20 Segment root5 场景中的 RCSD 替换口径，使人工确认满足锚定、拓扑、方向和有效 buffer 穿行条件的 RCSDRoad 能进入替换；同时确保未真正落地到目标 Segment 的 RCSDRoad 仍保留在未替换归因中。

## 2. 授权业务规则

- Segment 的关键路口包含 `pair_nodes` 和 required `junc_nodes`，两类路口都必须存在可消费的 SWSD-RCSD relation。
- RCSD Segment 必须能表达 SWSD Segment 中 pair/junc 的相对顺序、方向和拓扑关系；RCSD 自身额外经过未锚定路口不构成替换硬阻塞。
- RCSD Segment 不要求完全位于 SWSD Segment buffer 内；只有当 pair-to-pair 存在一条连续通路完全不经过 SWSD Segment buffer 时，才作为硬阻塞。
- RCSD 反向 buffer / reverse coverage 只作为替换后的人工风险审计项，不作为 Step2 replaceable 或 Step3 plan 的硬通过门槛。
- 已真实进入目标 Segment 最终 F-RCSD 的 RCSDRoad 不应继续出现在未替换归因中；仅可带人工审计风险标签。
- 若 RCSDRoad 被其它 Segment 消耗，或没有进入目标 Segment 的最终 F-RCSD，则目标 Segment 仍必须保留未替换归因。

## 3. 目标用户场景

### US1: 人工审计可替换的 RCSDRoad 正确落地

质检人员确认 `1206914_1257213` 下部分 RCSDRoad 满足 relation、拓扑、方向和有效 buffer 穿行条件后，T06 应将其发布为可替换 plan 并在 Step3 输出目标 Segment 可消费的 F-RCSD carrier。

验收：

- 当前已确认样例 `5384375261856127 / 5384391501217882 / 5378399788663308 / 5378399788663311` 不得被归为“已通过但未替换”或错误隐藏。
- 上次审计确认属于 `1206914_1257213` 的 9 条 RCSDRoad 若满足新口径，应进入目标 Segment 替换；否则必须保留明确未替换归因。

### US2: 未落地 RCSDRoad 不再漏归因

质检人员检查未替换清单时，任何未进入目标 Segment 最终 F-RCSD 的候选 RCSDRoad 都能在归因产物中找到，并区分“目标未落地”“被其它 Segment 消耗”“仍处于 plan 阻塞”等情况。

验收：

- 在最终 F-RCSD 中不存在、且未被目标 Segment relation 消费的 RCSDRoad 必须出现在 `t06_step3_unreplaced_rcsd_attribution.*`。
- 已被其它 Segment 消耗但未被目标 Segment 消费的 RCSDRoad，按目标 Segment 继续输出 class 5 未替换归因，并追加人工后审风险标签。

### US3: 误挂接风险可审计且可回归

当一个 RCSDRoad 同时被不相关 Segment 或 SWSD/RCSD 混合关系错误消费时，T06 输出必须能暴露该风险，且修复不能导致 `1885118` 和 T10 6 个基线用例业务效果回退。

验收：

- 对用户指出的 `520256607_1210397` 类误挂接，必须基于原始数据和当前输出给出是否成立的证据。
- 每个根因修复后必须先跑 Segment 级回归，再跑 `1885118`，最后跑 T10 6 case。

## 4. 职责视角

- 产品视角：输出必须支持人工审计判断哪些 RCSDRoad 已收益、哪些仍未落地、哪些仅带人工风险标签。
- 架构视角：Step2 仍是 replaceable 与 replacement plan 的权威层；Step3 只执行 plan，不重新扩大替换范围。
- 研发视角：改动应局限于 T06 源事实、Step2 口径、Step3 未替换归因和对应测试，不改 T01/T05 输入事实。
- 测试视角：必须覆盖单元测试、目标 Segment 回归、`1885118` 基线对比和 T10 6 case。
- QA 视角：必须显式记录 CRS/坐标变换、拓扑一致性、几何语义可解释性、审计可追溯性和性能可验证性。

## 5. 非目标

- 不回写 T05 relation。
- 不新增正式 CLI、脚本入口或长期工具。
- 不用局部人工真值反推新的上游字段语义。
- 不让 Step3 对 Step2 rejected Segment 自行搜索 RCSD Segment。
