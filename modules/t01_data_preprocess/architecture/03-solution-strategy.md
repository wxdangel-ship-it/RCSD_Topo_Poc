# 03 方案策略

本文件是 T01 的架构设计 / 需求具体实现策略说明。它解释 SWSD Segment 如何从输入 `nodes / roads` 落到双向 Segment、单向补段和 Step6 聚合输出。稳定输入输出、入口和参数以 `INTERFACE_CONTRACT.md` 为准；已确认 baseline 补充以 `architecture/accepted-baseline.md` 为准。

## 1. 总体策略

T01 采用“working layer -> 双向多阶段构段 -> 单向补段 -> Segment 聚合反查”的路径：

1. 先复制输入生成 working `nodes / roads`，初始化 `grade_2 / kind_2 / segmentid / sgrade`。
2. 在进入 Step1 前完成环岛预处理与极窄 strict-T bootstrap node retyping。
3. 用 Step1-Step5C 构建双向 Segment，并在每轮结束后刷新当前语义。
4. 在 Step5C refreshed 结果上执行单向补段 continuation，不回写双向 accepted baseline。
5. 用 Step6 聚合最终 Segment，输出 `segment.gpkg`、内部节点和冲突审计。

正确路径是让每个 Segment 的 pair、body、trunk、stage、错误与未构段 road 都可追溯。错误路径是把候选、调试结果或单向补段结果反向覆盖已确认的双向 baseline。

## 2. Working Layer 初始化

### 2.1 业务目的

建立与输入隔离的工作层，让后续规则只操作当前模块语义字段，不直接改写原始输入。

### 2.2 输入与前提

- `nodes.gpkg`：至少包含 `id / mainnodeid / closed_con / grade / kind`。
- `roads.gpkg`：至少包含 `id / snodeid / enodeid / direction / formway / road_kind`，可选 `kind / roadtype`。

### 2.3 落地策略

- working nodes 复制输入，并初始化 `grade_2 = grade`、`kind_2 = kind`。
- working roads 复制输入，并初始化 `segmentid = null`、`sgrade = null`。
- 后续业务判断统一使用 `grade_2 / kind_2`。
- 原始 `grade / kind` 保留为输入事实，不作为后续强规则主字段；`Road.kind` 仅在已确认的局部续行规则中按前两位道路等级使用。

### 2.4 输出与审计

- working `nodes / roads`。
- summary 中记录字段初始化、输入计数和 CRS 信息。

### 2.5 对错边界

- 对：working 字段和原始字段职责分离。
- 错：直接修改输入文件，或用 raw `grade / kind` 替代 `grade_2 / kind_2` 进入后续强规则。

## 3. 环岛预处理与 Bootstrap Retyping

### 3.1 业务目的

在正式构段前修正会影响全链路 seed / terminate 判定的基础语义。

### 3.2 输入与前提

- 环岛识别依赖 `roadtype bit3` Road 的共享 node 拓扑连通。
- bootstrap retyping 只针对极窄 strict-T 纠错。

### 3.3 落地策略

- 环岛只按共享 node 连通聚合，不按几何距离或 buffer 聚合。
- 每组环岛 road 及其关联 nodes 形成一个语义路口，组内最小 node id 为 mainnode。
- 环岛 mainnode 写 `grade_2=1 / kind_2=64`，成员写 `grade_2=0 / kind_2=0`，全组 `mainnodeid` 统一为 mainnode。
- 环岛 mainnode 后续不参与 generic node refresh。
- bootstrap retyping 只允许把严格满足条件的 `grade_2=1 / kind_2=4` 当前节点修正为 `grade_2=2 / kind_2=2048`。

### 3.4 输出与审计

- 刷新后的 working nodes。
- 环岛组、bootstrap 命中、未命中原因和修正计数。

### 3.5 对错边界

- 对：环岛和 strict-T 只在确认条件下修正。
- 错：把单点环岛、近邻几何或未确认 T 型形态泛化为强修复。

## 4. Step1：Pair Candidate Search

### 4.1 业务目的

在当前轮输入规则下寻找可能构成 Segment 的 pair candidate。

### 4.2 输入与前提

- 首轮规则：`grade_2 in {1}`、`kind_2 in {4,64}`、`closed_con in {2,3}`。
- Road 过滤：双向 Step1-Step5C 使用 `road_kind != 1` 且 `formway != 128`。

### 4.3 落地策略

- 将合法语义路口作为 seed / terminate，through 节点继续追溯。
- `kind_2=128` 在双向首轮代表复杂分歧 / 合流 mainnode 组；该组内部按物理 node 级恢复分歧 / 合流语义，不把 `through_node_ids` 扩展为复杂路口标签。
- 分歧 / 合流局部续行先按 `Road.kind` 前两位道路等级保留同等级出口，再用方向夹角做二级消歧。

### 4.4 输出与审计

- `pair_candidates`。
- candidate 经过复杂组、局部续行和预算相关的审计字段。

### 4.5 对错边界

- 对：Step1 只输出候选，不代表最终有效 Segment。
- 错：把 Step1 candidate 直接发布为 Segment，或用几何形态反推缺失的 Road 等级。

## 5. Step2：Pair Validation 与 Segment Body

### 5.1 业务目的

对 Step1 候选做 validated / rejected 判定，形成 pair-specific trunk 和 segment body。

### 5.2 输入与前提

- 消费 Step1 `pair_candidates`。
- 当前轮合法 seed / terminate 不得被 through node 吞掉。

### 5.3 落地策略

- 先完成 single-pair validation，再做 same-stage pair arbitration，避免固定顺序先到先得。
- 对复杂 `kind_2=128` 组合优先采用局部 port corridor 判定；命中但门禁失败时直接 rejected，不回退到复杂组内部全局追溯。
- 对 trunk path 的内部多路口面节点执行转向角 gate：只有 incident road 数不少于 3 的语义路口才检查，超过 `60°` 的进入 / 离开夹角视为非自然 continuation 并 rejected；二度普通弯曲不触发该 gate。
- `non-trunk component` 触达其它 terminate 或吃到其它 validated pair trunk 时，不进入当前 `segment_body`。
- trunk search budget 是兜底保护；超限必须 rejected 并记录预算、消耗和 candidate/pruned 体量。

### 5.4 输出与审计

- `validated`
- `rejected`
- `trunk`
- `segment_body`
- `step3_residual`

### 5.5 对错边界

- 对：final segment 只表达当前 validated pair 的 pair-specific road body。
- 错：把 all related roads、其它 pair trunk、内部路口面明显转向或预算超限结果纳入 Segment body。

## 6. Step3：Working 语义刷新

### 6.1 业务目的

基于 Step2 结果刷新当前工作图，为后续 residual graph 扩展提供新语义。

### 6.2 落地策略

- 当前轮 validated pair 端点保持当前语义。
- 所有 road 都在一个 Segment 中的 node 写为 `grade_2=-1 / kind_2=1`。
- 唯一 Segment + 其余全是右转专用道的 node 写为 `grade_2=3 / kind_2=1`。
- 唯一 Segment + 其它非 Segment road 同时存在 in/out 时，执行 family-based retyping。
- Step2 新构成 road 写 `sgrade=0-0双`。

### 6.3 对错边界

- 对：每轮刷新只基于已确认的构段结果。
- 错：环岛 mainnode 被 generic refresh 改写，或 right-turn-only 语义被当作普通 residual。

## 7. Step4 / Step5A / Step5B / Step5C：Residual Graph 扩展

### 7.1 业务目的

在不同等级和 residual 条件下逐轮扩展双向 Segment，覆盖 Step2 未能处理的可构段 road。

### 7.2 落地策略

- Step4 输入 `grade_2 in {1,2}`、`kind_2 in {4,64,2048}`、`closed_con in {2,3}`。
- Step4 结束后立即 refresh；两端 `grade_2=1` 的 validated pair 允许写 `sgrade=0-0双`，并用 `segment_build_source=step4_high_grade_terminal_demotion` 标记 Step6 豁免来源。
- Step5A / Step5B / Step5C 按顺序执行，每个子阶段结束后立即 refresh。
- 历史高等级边界并入当前 hard-stop，来源优先为上一轮 validated endpoints。
- Step5C 使用 rolling endpoint pool 和 demotable endpoint set，不再把所有历史 endpoint 都视为 actual barrier。

### 7.3 输出与审计

- 新增或刷新后的 `nodes / roads`。
- 各阶段 validated / rejected、segment body、refresh summary 和来源字段。

### 7.4 对错边界

- 对：各子阶段基于上一阶段 refreshed 结果推进。
- 错：跨越历史高等级边界，或让低等级 residual 重写当前已成立的高等级 Segment。

## 8. Step5 后单向补段

### 8.1 业务目的

补齐双向流程之后仍未构段的单向 road 与受控 residual road bundle。

### 8.2 输入与前提

- 只在 Step5C refreshed `nodes / roads` 后执行。
- 仅处理仍未被双向 Segment 构成的 road。
- 继续排除 `formway=128` 和右转专用道。
- 单向阶段允许 `road_kind=1`，但该放开不回写双向 Step1-Step5C。

### 8.3 落地策略

- 常规单向 terminate-to-terminate 追踪按 `0-0单 / 0-1单 / 0-2单` 阶段执行。
- dead-end leaf 只处理一端合法语义端点、另一端无其它有效延展的单条双向 road 或方向互补单向 road bundle。
- residual corridor fallback 在 final single-road fallback 之前执行；只消费仍未构段、端点可解析、非右转专用、非 `formway=128` 的 residual road，并只穿越当前 residual candidate 图中 incident road 数为 2 的语义节点。该阶段不使用 `node_lid/cross_lid` 历史字符串判定度数，不争占已构成的主干 Segment。
- final single-road fallback 只处理仍未构段且端点可解析的 road，不放宽前序 terminate 规则。
- final side-attachment merge 只把符合挂接和距离条件的候选 Segment 并入同一个 `0-0双` 主 Segment，并保留 `pre_merge_*` 审计字段。
- Segment 形态控制在 side-attachment merge 之后、Step6 之前执行；它只处理双向 Segment，并在真实多路口内部出现大于 `60°` 转向，或源 Segment 仅含两条 road 且两侧最高道路等级不一致时拆分，保留 `pre_shape_control_*` 审计字段。

### 8.4 输出与审计

- `oneway_segment_roads.gpkg`
- `oneway_segment_build_table.csv`
- `oneway_segment_summary.json`
- `unsegmented_roads.gpkg/csv/json`

### 8.5 对错边界

- 对：单向补段只补齐尾部未构段 road。
- 对：Step6 前形态控制只用已启用字段拆分可解释的双向 Segment 贯穿问题。
- 错：用单向补段改变双向构段规则或 active freeze baseline。
- 错：仅因 Segment 长度较长就切段。

## 9. Step6：Segment 聚合与反查

### 9.1 业务目的

将最终 working roads 聚合为正式 Segment，并输出内部节点和冲突审计。

### 9.2 落地策略

- `segment.gpkg` 按 `segmentid` 聚合 MultiLineString，并输出 `id / sgrade / pair_nodes / junc_nodes / roads`。
- `pair_nodes` 按 `segmentid A_B` 解析；端点 `mainnodeid` 为空时回退 node 自身 id。
- 内部高等级 `grade_2=1 / kind_2=4` 节点会触发 `grade_kind_conflict`，但 Step4 高等级降级来源标记可审计豁免。
- 单向 Segment、dead-end leaf Segment 不适用部分双向提升规则。

### 9.3 输出与审计

- `segment.gpkg`
- `inner_nodes.gpkg`
- `segment_error.gpkg`
- `segment_error_s_grade_conflict.gpkg`
- `segment_error_grade_kind_conflict.gpkg`

### 9.4 对错边界

- 对：冲突显式输出并可按来源解释。
- 错：静默修正 `sgrade` 或忽略内部高等级路口冲突。

## 10. Freeze Compare 与证据包

- freeze compare 主要保护双向 accepted baseline。
- 最终运行目录可包含新增单向 Segment，但不作为双向 baseline compare 主判定对象。
- 文本证据包用于内外网结果回传和轻量审计，不替代正式 CLI 契约。
