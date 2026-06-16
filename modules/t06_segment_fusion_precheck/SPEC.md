# T06 模块规格：RCSDSegment 构建与 Segment 替换

## 1. 模块定位

T06 消费 T01 SWSD Segment 与 T05 SWSD-RCSD 语义路口关系，构建 RCSDSegment 候选，在 Step2 发布统一 replacement plan 与问题回流注册表，并在 Step3 按 plan 输出融合后的 F-RCSD Road / Node。T06 是从关系建模进入数据替换的承接模块，也是 T09 在 F-RCSD 上恢复 restriction 的直接上游。

## 2. 业务目标

- 从 T01 `segment.gpkg` 中识别可参与融合的 SWSD Segment。
- 基于 T05 relation 与 copy-on-write RCSD 网络构建 buffer-based RCSDSegment。
- 输出经过硬审计与特殊路口组门控后的 replaceable 集合，并发布 `t06_segment_replacement_plan.*` 作为 Step3 的正式执行范围。
- 输出 `t06_segment_replacement_problem_registry.*`，把未替换或由当前计划覆盖的问题按根因和建议归属回流到 T01/T03/T04/T05/T08/T06 或数据裁剪审计。
- Step3 优先消费 Step2 replacement plan 执行替换，旧 replaceable + group/special audit 只作为兼容 fallback。
- 对失败 Segment 输出诊断、候选修复证据和上游责任归因；默认不覆盖 T05 relation，但 pair anchor 锚定错误在满足受限高置信安全门槛时，可在 T06 当前 Segment 内使用候选 pair 执行一次自动重试；普通缺失 pair 端点补全必须保留 T05 已知端点所在 SWSD pair 侧，只补失败侧；高等级 single 当缺失端点同时伴随已知端点被 `candidate_anchor_mismatch` 判错时，必须由诊断明确覆盖两个 SWSD pair 端点并通过正式硬审计后，才可整体采用候选 pair；两端 pair relation 均缺失时，只允许非人工复核、连通与方向评分满分、shape similarity 不低于 `0.95` 的 buffer-only 候选 pair 进入正式硬审计重试。
- 对高等级 Segment 的裁剪窗口不足失败，允许在 T05 原始 pair relation 不变且全图拓扑证据充分时执行受限重审；单向采用 RCSD graph-first 纵向联通并要求经过 50m buffer core，双向优先采用 adaptive buffer，必要时采用 dual graph-first 双向联通且不得跨越额外 mapped semantic nodes；重审通过仍必须满足全部硬审计并输出实际审计来源。

## 3. 当前范围

### 3.1 正式支持

- Step1：识别 SWSD Segment 候选和最终 fusion units。
- Step2：基于 buffer-based 策略构建 RCSDSegment 候选和 replaceable，并发布 replacement plan / problem registry。
- Step3：消费 replacement plan 执行 Segment 替换，输出 F-RCSD Road / Node。
- `kind_2=64 / 128` 特殊路口组门控。
- buffer-only probe、repair candidates 与 failure business audit。
- 高等级 single graph-first 纵向联通、dual adaptive buffer 与 dual graph-first 双向联通重审审计。
- 内网脚本和文本证据包 helper。

### 3.2 当前非目标

- 不修改 T01 / T05 输出。
- 不新增 repo CLI。
- Step3 不处理 Step2 rejected Segment。
- Step3 不通过几何猜测补救未通过 Step2 的 Segment。
- Step2 不再执行旧 pair-to-pair BFS、主轴趋势、长度趋势或唯一性筛选。

## 4. 上下游关系

| 方向 | 模块 / 数据 | 关系 |
|---|---|---|
| 上游 | T01 | 提供 SWSD `segment.gpkg`、`roads.gpkg`、`nodes.gpkg`。 |
| 上游 | T05 | 提供 `intersection_match_all.geojson`、`rcsdroad_out.gpkg`、`rcsdnode_out.gpkg`。 |
| 下游 | T09 | 消费 F-RCSD Road/Node 与 SWSD-FRCSD Segment relation 进行 restriction 投影。 |
| 下游 | T10 | 以文件 handoff 方式组织 T06 输出的 Case 证据。 |

## 5. 输入

| 输入 | 用途 |
|---|---|
| T01 `segment.gpkg` | Step1 候选 Segment、`pair_nodes / junc_nodes / roads / swsd_directionality` 来源。 |
| SWSD `roads.gpkg / nodes.gpkg` | Step1/Step3 删除和保留 SWSD Road/Node 的来源。 |
| T05 `intersection_match_all.geojson` | Step2 将 SWSD pair/junc 映射到 RCSD 语义路口。 |
| T05 `rcsdroad_out.gpkg / rcsdnode_out.gpkg` | Step2 RCSD 建图和 Step3 引入 RCSD Road/Node 的来源。 |
| `t06_segment_replacement_plan.*` | Step3 优先消费的统一执行计划；旧产物无 plan 时才回退读取 passed 特殊路口组和 group replacement 审计。 |

## 6. 输出

| 输出 | 用途 |
|---|---|
| `t06_swsd_segment_candidates.*` | 通过 EVD 基础检查的 SWSD Segment 候选。 |
| `t06_swsd_segment_final_fusion_units.*` | 通过 anchor / fallback 检查的最终 SWSD fusion units；高等级 Segment 中被脱挂的非特殊 junc-only 节点记录在 `detached_junc_nodes / detached_junc_reasons`。 |
| `t06_rcsd_segment_candidates.*` | buffer 成功构建的 RCSDSegment 候选。 |
| `t06_rcsd_segment_replaceable.*` | 经过硬审计与特殊组门控后的最终可替换集合。 |
| `t06_rcsd_segment_rejected.*` | Step2 拒绝原因和审计。 |
| `t06_special_junction_group_audit.*` | 环岛 / 复杂路口组级门控审计。 |
| `t06_segment_replacement_plan.*` | Step2 发布的正式 Step3 执行计划，覆盖标准 replaceable、passed 特殊路口组内部 RCSD 对象和 passed path-corridor group replacement。 |
| `t06_segment_replacement_problem_registry.*` | Segment 替换问题注册表，记录已由当前 plan 覆盖、已由 Step2 标准计划解决或仍需上游迭代的问题。 |
| `t06_frcsd_road.* / t06_frcsd_node.*` | Step3 F-RCSD 替换结果。 |
| `t06_step3_unreplaced_rcsd_roads.*` | 未进入替换结果的 RCSDRoad 审计。 |

## 7. 关键业务步骤

| 步骤 | 业务说明 |
|---|---|
| Step1 eligibility | 解析 `pair_nodes + junc_nodes`，先排除 `pair_nodes` 两端相同的非替换主通道，再基于 `has_evd / is_anchor` 识别候选与 final fusion units。 |
| Step2 relation mapping | 用 T05 relation 映射 pair required nodes，optional junc 只做审计和受控约束。 |
| Step2 buffer candidate | 以 SWSD Segment 50m buffer 筛选 RCSDRoad/RCSDNode 候选。 |
| Step2 corridor 构建 | 基于 pair required semantic nodes 构建最小 corridor 子图，不直接发布连通分量。 |
| Step2 pruning / hard audit | 裁剪 out seeds，检查叶子端点、双向 / 单向可达、buffer overlap 和额外 mapped semantic nodes。 |
| 高等级受限重审 | 对 `0-0* / 0-1*` Segment 的裁剪窗口不足失败，在原始 pair relation 不变时执行受限重审；single 以 RCSD 有向图联通 pair 路口并经过 50m buffer core，dual 优先 adaptive 到 125m，仍失败时可在不跨越额外 mapped semantic nodes 的前提下执行 dual graph-first 双向联通。 |
| 特殊组门控 | 环岛和复杂路口关联 Segment 必须全组可替换，否则整组移出 replaceable。 |
| Step2 replacement plan | 把标准 replaceable、特殊组内部对象、path-corridor group replacement 统一发布为 Step3 执行计划。 |
| Step2 problem registry | 将 rejected、当前 plan 覆盖和 Step2 自动解决的问题登记为可回流上游模块的审计记录。 |
| Step3 替换 | 按 replacement plan 删除被替换 SWSDRoad 和端点 Node，引入 retained RCSDRoad/RCSDNode；若 Step1 detached junc 仍触达原 SWSDRoad，则以 `source=2` 保留为局部 restriction carrier，并重建语义路口 C。 |

## 8. 什么是对

- Step2 只接受 `status=0 / base_id>0` 的 T05 relation。
- Step1 final fusion units 只包含 `pair_nodes` 两端不同的 SWSD Segment；T01 `oneway_single_road_fallback` 生成的同一语义路口内部 self-pair fallback 必须进入 Step1 rejected 审计，不进入 Step2 替换分母。高等级 `0-0* / 0-1*` Segment 中，`has_evd=yes` 且 `is_anchor` 明确不可用的 `pair_nodes.kind_2=2048`、`junc_nodes.kind_2 in {16,2048}` 可被放行到 Step2 probe；`sgrade=0-2双` 且两个 `pair_nodes.kind_2` 均为 `2048` 的虚拟 T 型 pair 也可仅对 pair 主通道放行到 Step2 probe。上述放行都不被视为 anchor 成功，不回写 T05 relation。
- `pair_nodes` 是 hard required，`junc_nodes` 是 optional 内部通过 + 侧向阻断。
- retained RCSD graph 的叶子端点只能是 pair 对应 RCSD semantic nodes。
- 单向 Segment 的 source/target 只能由 SWSDRoad directed graph 推导。
- 高等级受限重审不能修改 T05 pair anchor，且通过后必须记录 `adaptive_buffer_status / adaptive_buffer_distance_m / adaptive_buffer_source_reason`；single 的 `adaptive_buffer_source_reason` 以 `single_graph_first_longitudinal_retry:` 前缀标识。
- buffer-only probe 若给出非 ambiguous、非人工复核的 `high_confidence_pair_anchor_candidate`，即使 T05 两端已有 anchor 但一端或两端被诊断为 `candidate_anchor_mismatch`，或 T05 两端 pair relation 均缺失但候选 pair 满足高置信安全门槛，也只允许在 T06 当前 Segment 内构造候选 effective relation 并重新执行正式 extractor；重试失败仍保持 rejected，不回写 T05 relation。
- 单向 `multi_anchor_ambiguous` 只能在 probe 高置信、oriented RCSD pair 与 SWSD Segment 轴向端点侧位一致、且正式试算恰好一个 oriented candidate 通过时自动替换；多个候选通过、无候选通过或硬审计失败必须保持 rejected / 人工复核。
- Step3 只执行 Step2 replacement plan，不重新判定特殊组或 path-corridor group 可替换性；若标准 replaceable 的 final junc 集合相对 T01 原始 Segment 发生 detached junc 缩减，detached junc 触达的原 SWSDRoad 必须保留为 `source=2` 局部 carrier，并在 relation 中标记 `replaced+retained_swsd`。

## 9. 什么是错

- 用 buffer 连通分量直接作为 RCSDSegment。
- 未满足高置信安全门槛时，用 repair candidate 覆盖 T05 relation 并继续生成 replaceable。
- 将 `candidate_anchor_mismatch` 直接视为 T05 relation 修正并绕过 Step2 buffer / direction / geometry / 叶子端点 / 特殊组硬审计。
- 用高等级受限重审绕过 direction、geometry、叶子端点、额外 mapped semantic node 或特殊组硬审计。
- 用 `pair_nodes` 字段顺序或 `segmentid A_B` 顺序推断单向 direction。
- 绕过 Step2 replacement plan 对 rejected Segment 执行 Step3 替换。
- 将 detached junc 的 `identity_retained_swsd` node map 解释成 RCSD 锚定成功，或因此回写 T05 relation。
- 因 SWSD/RCSD 原始 `id` 冲突而重写 ID；应依赖 `source` 区分并输出 collision audit。

## 10. 当前治理缺口

- 架构目录仍保留旧 `02-business-rules / 03-input-output-contract / 04-algorithm-strategy`，本轮新增标准 `architecture/04-solution-strategy.md` 后，旧文件应作为兼容参考逐步收敛。
- Step3 输出的 SWSD-FRCSD Segment relation 需持续与 T09 输入契约保持同步。
