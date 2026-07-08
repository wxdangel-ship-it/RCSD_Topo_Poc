# T01 Segment 形态控制业务迭代 Spec

## 背景

当前最新主干已经在 T01 Step2/4/5 中加入内部转角控制与单向过路口阻断，但 1885118 基线仍能观察到部分最终 Segment 在语义路口内形成过长、拐折或分叉并入的形态，导致 T06 中 `required_semantic_nodes_not_connected_in_buffer`、`rcsd_not_bidirectional_for_swsd_dual`、`invalid_junc_relation_status` 等失败更难被替换。

本轮目标不是按长度硬切 Segment，而是在 T01 发布 Segment 前，用已正式启用的语义节点、道路等级和几何方向信息识别“跨语义交叉路口仍贯穿”的不合理 Segment，并把其拆成更可解释、可追溯的子 Segment。最终以 T06 替换结果不回退为验收。

## 用户故事

### US1 双向 Segment 不应跨明显转向的语义交叉路口

作为 T06 Segment 替换使用者，我希望 T01 双向 Segment 在内部语义交叉路口出现明显转向时被拆成两个子 Segment，避免一个长 Segment 同时覆盖两段业务方向不同的通路。

验收：
- 当内部语义交叉路口两侧道路夹角大于 60 度，且该路口为真实多路口时，Segment 必须在该路口切分。
- 当两条 road 构成的短双向 Segment 在内部语义交叉路口两侧主干道路等级不一致时，Segment 必须在该路口切分；多 road 长链路不得仅因局部等级差异切分。
- 近直行、同等级、拓扑连续的走廊不得仅因长度变长被拆分。

### US2 单向 Segment 不应扩大贯穿同等级交叉路口或吸附侧向旁路

作为 T01 成果审计者，我希望单向 Segment 继续遵守既有同等级交叉路口阻断和 side-attachment merge 审计口径；本轮不得扩大单向侧向挂接禁止规则，除非 T06 对比证明不会造成 RCSD 替换回退。

验收：
- 单向 trace 继续遵守既有内部交叉路口阻断规则。
- 形态控制阶段不新增单向侧向旁路合并；既有 side-attachment merge 结果必须保留审计字段并进入 T06 对比。
- 若发生切分或保留，输出必须能说明触发节点、触发原因和影响 road。

### US3 以 T06 替换结果作为主验收

作为回归负责人，我希望优化后的 T01 成果在 1885118 上先证明有效，再扩展到 Segment20 和其余 5 个本地用例，且 T06 Segment 替换与 RCSD 替换结果不回退。

验收：
- 1885118 必须完成 T01/T06 rerun，并与当前最新基线对比。
- 1885118 通过后，必须执行 Segment20 与 `605415675`、`609214532`、`706247`、`74155468`、`991176` 回归。
- 若 T01 Segment 数变化但 T06 关键替换指标不回退，视为可接受；若 T06 指标回退，必须定位到具体 Segment 变化。

## 功能需求

- FR-001: T01 MUST 在 Step6 聚合发布前执行 Segment 形态控制，输入为当前工作层 road/node 记录与 `segmentid/sgrade`。
- FR-002: 形态控制 MUST 仅使用已正式启用的字段：`closed_con`、`kind_2`、`grade_2`、`Road.kind`、road geometry、working mainnode 映射，不得引入未契约化字段。
- FR-003: 双向 Segment 的内部语义节点若满足真实多路口条件，且相邻子路径夹角大于 60 度，MUST 在该节点拆分。
- FR-004: 双向 Segment 的内部语义节点若两侧子路径主干道路等级不一致、节点为真实多路口，且源 Segment 仅由两条 road 构成，MUST 在该节点拆分；多 road 长链路只可由 FR-003 的转角规则单独触发。
- FR-005: 形态控制 MUST NOT 按 Segment 长度单独触发拆分。
- FR-006: 形态控制 MUST 跳过无法稳定解析 pair endpoint、缺失端点 node、缺失 road geometry 或拓扑不连通的 Segment，并输出审计原因，不得 silent fix。
- FR-007: 发生拆分时，MUST 保留每条 road 的拆分前 `segmentid/sgrade/build_source`，并写入新的审计字段说明切分节点与原因。
- FR-008: 发生拆分时，MUST 生成稳定的新 `segmentid`，不得与现有 Segment 冲突。
- FR-009: 形态控制不得新增单向侧向旁路合并规则；既有 side-attachment merge 必须保留审计字段以便 T06 对比，单向禁止口径作为后续待确认项处理。
- FR-010: T01 summary MUST 增加形态控制统计，包括扫描 Segment 数、拆分 Segment 数、影响 road 数、跳过原因、触发原因。

## 非功能需求

- CRS：验证必须记录输入 CRS；形态控制不做 CRS 猜测或坐标 silent fix。
- 拓扑：形态控制只在 road-node 拓扑可解释时执行，拓扑缺失必须审计跳过。
- 几何语义：拆分依据必须能回溯到语义节点、道路等级和相邻 road 夹角。
- 审计：输出需包含 baseline/after 的 Segment count、T06 Step2/Step3 替换指标、关键退化 Segment 明细。
- 性能：1885118、Segment20 和其余 5 case 的运行时不得出现异常数量级增长；新增逻辑应按 Segment 内部局部图处理。

## 非目标

- 不修改 T06 业务口径或替换计划逻辑。
- 不新增官方 CLI、scripts、Makefile 入口。
- 不根据本轮局部样本反推新的上游字段语义。
- 不更新 active freeze 指针，除非本轮验证产物完整通过并在回报中明确说明。
