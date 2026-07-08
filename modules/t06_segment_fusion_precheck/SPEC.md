# T06 模块规格：RCSDSegment 构建与 Segment 替换

## 1. 模块定位

T06 消费 T01 SWSD Segment 与 T05 SWSD-RCSD 语义路口关系，构建 RCSDSegment 候选，在 Step2 发布统一 replacement plan 与问题回流注册表，并在 Step3 按 plan 输出融合后的 F-RCSD Road / Node。T06 是从关系建模进入数据替换的承接模块，也是 T09 在 F-RCSD 上恢复 restriction 的直接上游。

## 2. 业务目标

- 从 T01 `segment.gpkg` 中识别可参与融合的 SWSD Segment。
- 基于 T05 relation 与 copy-on-write RCSD 网络构建 buffer-based RCSDSegment。
- 输出经过硬审计与特殊路口组局部替换门控后的 replaceable 集合，并发布 `t06_segment_replacement_plan.*` 作为 Step3 的正式执行范围。
- 输出 `t06_segment_replacement_problem_registry.*`，把未替换或由当前计划覆盖的问题按根因和建议归属回流到 T01/T03/T04/T05/T08/T06 或数据裁剪审计。
- Step3 优先消费 Step2 replacement plan 执行替换，旧 replaceable + group/special audit 只作为兼容 fallback。
- 对失败 Segment 输出诊断、候选修复证据和上游责任归因；默认不覆盖 T05 relation，但 pair anchor 锚定错误在满足受限高置信安全门槛时，可在 T06 当前 Segment 内使用候选 pair 执行一次自动重试；普通缺失 pair 端点补全必须保留 T05 已知端点所在 SWSD pair 侧，只补失败侧；高等级 single 当缺失端点同时伴随已知端点被 `candidate_anchor_mismatch` 判错时，必须由诊断明确覆盖两个 SWSD pair 端点并通过正式硬审计后，才可整体采用候选 pair；两端 pair relation 均缺失时，只允许非人工复核、连通与方向评分满分、shape similarity 不低于 `0.95` 的 buffer-only 候选 pair 进入正式硬审计重试。
- 对高等级 Segment 的裁剪窗口不足失败，允许在 T05 原始 pair relation 不变且全图拓扑证据充分时执行受限重审；单向采用 RCSD graph-first 纵向联通并要求经过 50m buffer core，双向优先采用 adaptive buffer，必要时采用 dual graph-first 双向联通；重审通过仍必须满足方向、required junction 相对拓扑、有效 buffer 穿行和特殊组门控，并输出实际审计来源。
- 在 50m buffer 覆盖通过后继续执行窄通道视觉连续性复核，防止 RCSD 虽然处在宽 buffer 内、但实际替换后主线目视断裂或明显偏离 SWSD 主通道。
- Step3 在不重判可替换性的前提下处理真实数据差异：正式替换道路保持 RCSD source 边界，保留 SWSD carrier 只作为局部通行承载和风险审计；提前右转挂接、端点补齐、surface-assisted node closure、surface-aware retained-junction gate 风险释放和最终 topology connectivity audit 用于提高 F-RCSD 可用性。

## 3. 当前范围

### 3.1 正式支持

- Step1：识别 SWSD Segment 候选和最终 fusion units。
- Step1 可消费 T05 Phase 2 audit 中的 `T11_MANUAL` 人工正向 relation，用于释放对应 `is_anchor=fail3/fail4` 的锚定失败，或释放人工确认的 `has_evd=no / missing` no-evidence relation 进入 Step2 审查；该规则不改变节点事实，也不绕过 Step2/Step3 硬审计。
- Step2：基于 buffer-based 策略构建 RCSDSegment 候选和 replaceable，并发布 replacement plan / problem registry。
- Step3：消费 replacement plan 执行 Segment 替换，输出 F-RCSD Road / Node。
- `kind_2=64 / 128` 特殊路口组局部替换门控。
- buffer-only probe、repair candidates 与 failure business audit。
- 高等级 single graph-first 纵向联通、dual adaptive buffer 与 dual graph-first 双向联通重审审计。
- Step2 窄通道视觉连续性复核。
- Step3 source 边界审计、提前右转后处理、端点补齐、surface topology closure 和 topology connectivity audit。
- 内网脚本和文本证据包 helper。

### 3.2 当前非目标

- 不修改 T01 / T05 输出。
- 不新增 repo CLI。
- Step2 对 reverse coverage / buffer 覆盖差异必须按受控审计风险处理：正式 relation 已消费、pair + required junction graph / candidate graph / 方向性全部通过，且 pair-to-pair 不存在完全绕开 SWSD Segment buffer 的连续通路时，可发布 replacement plan，并写入 `manual_review_required` 风险；该路径允许 RCSD 局部跑出 buffer，不要求 retained RCSD corridor 完全位于 SWSD 50m buffer 内。
- Step3 不处理未进入 Step2 replacement plan 的 rejected Segment。
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
| T05 `intersection_match_all.geojson` 及同目录 audit | Step1 可读取 T05 audit 中可消费的 `T11_MANUAL` 人工正向 relation 释放 `fail3/fail4` anchor gate，或释放人工确认的 no-evidence relation；Step2 将 SWSD pair/junc 映射到 RCSD 语义路口。 |
| T05 `rcsdroad_out.gpkg / rcsdnode_out.gpkg` | Step2 RCSD 建图和 Step3 引入 RCSD Road/Node 的来源。 |
| `t06_segment_replacement_plan.*` | Step3 优先消费的统一执行计划；旧产物无 plan 时才回退读取 passed 特殊路口组和 group replacement 审计。 |
| T03/T04/T05/T07 surface 与 T04 audit | Step3 可选 surface topology closure 输入；用于节点语义闭合、relation node map 补写和旧 plan 兼容审计，不作为通用替换道路白名单。准确 T05 relation 下 retained-junction 20m 距离 gate 的风险释放由 Step2 replacement plan 前置处理。 |

## 6. 输出

| 输出 | 用途 |
|---|---|
| `t06_swsd_segment_candidates.*` | 通过 EVD 基础检查的 SWSD Segment 候选。 |
| `t06_swsd_segment_final_fusion_units.*` | 通过 anchor / fallback 检查的最终 SWSD fusion units；高等级 Segment 中被脱挂的非特殊 junc-only 节点记录在 `detached_junc_nodes / detached_junc_reasons`。 |
| `t06_rcsd_segment_candidates.*` | buffer 成功构建的 RCSDSegment 候选。 |
| `t06_rcsd_segment_replaceable.*` | 经过硬审计与特殊组局部替换门控后的最终可替换集合。 |
| `t06_rcsd_segment_rejected.*` | Step2 拒绝原因和审计。 |
| `t06_special_junction_group_audit.*` | 环岛 / 复杂路口组级门控审计。 |
| `t06_segment_replacement_plan.*` | Step2 发布的正式 Step3 执行计划，覆盖标准 replaceable、全部通过特殊路口组内部 RCSD 对象和 passed path-corridor group replacement。 |
| `t06_segment_replacement_problem_registry.*` | Segment 替换问题注册表，记录已由当前 plan 覆盖、已由 Step2 标准计划解决或仍需上游迭代的问题。 |
| `t06_step2_progress.jsonl / t06_step2_heartbeat.json / t06_step2_slow_units.jsonl / t06_step2_slow_groups.jsonl / t06_step2_stackdump.log` | Step2 在 `progress=True` 时输出的运行诊断 sidecar，用于内网长耗时任务定位当前 Segment、group_audit 当前组、当前后处理阶段、逐文件写出状态、慢单元、慢 group 和 SIGUSR1 栈转储；不作为替换业务成果或 Step3 输入。 |
| `t06_frcsd_road.* / t06_frcsd_node.*` | Step3 F-RCSD 替换结果；GPKG/CSV 是稳定审计载体，feature JSON 默认不写出；`t06_frcsd_node.*` 可写入 `semantic_junction_group_id`，表达物理节点分离但语义同一路口的分组。 |
| `t06_step3_semantic_junction_groups.*` | Step3 基于 T05 有效 `target_id -> base_id` 关系输出的语义路口组审计，覆盖远距离 SWSD/RCSD 多源节点分裂风险。 |
| `t06_step3_unreplaced_rcsd_roads.*` | 未进入替换结果的 RCSDRoad 基础清单。 |
| `t06_step3_unreplaced_rcsd_attribution.* / t06_step3_unreplaced_rcsd_attribution_summary.json` | 未替换 RCSDRoad 的反向归因审计；保留 `attribution_*` 漏斗粗口径，并以 `final_attribution_*` 输出强证据优先、几何主 Segment 优先后的最终六类归因。几何主 Segment 在 relation scope 内时还需区分：已在可替换范围但 road 未被精确引用的回到 `5`，未进入可替换范围且 required semantic nodes / anchor 语义闭合不足的回到 `3`，RCSD 方向性/承载能力不足的保留 `4`。PPT 三大类以 `ppt_attribution_*` 输出：`4/5 -> Segment下RCSD质量导致无法替换`、`2/3 -> Segment侧替换前提不满足导致无法替换`、`1 -> RCSD不在Segment范围内导致无法替换`；mixed 部分覆盖不新增归因类型，只以低置信与 `ppt_review_flag` 标记。summary 输出 total-RCSD 分母下的数量与里程统计。 |
| `t06_step3_swsd_frcsd_segment_relation.*` | 所有 SWSD Segment 到 F-RCSD carrier 的稳定关系索引，区分 `replaced / replaced+retained_swsd / retained_swsd / failed`；`frcsd_road_ids` 必须指向最终存在的 F-RCSD Road，按 `source_mix / frcsd_road_source_values` 区分 RCSD 替换 carrier 与保留 SWSD carrier。 |
| `t06_step3_topology_connectivity_audit.*` | Step3 最终道路-节点完整性、正式替换 source 一致性、Segment 内连通、路口映射和挂接质量审计。 |
| `t06_step3_surface_topology_audit.*` | 可选 surface-assisted closure 审计，记录 T03/T04/T05/T07 surface 对节点闭合的贡献和阻断原因。 |
| `t06_step3_summary.json / t06_step3_detail_metrics.json / t06_step3_output_manifest.json` | Step3 紧凑 summary、详细指标 sidecar 与输出文件清单。summary 只保留下游常用漏斗、状态计数和 surface-aware 计数级结果；大体量列表、完整路径和文件大小进入 detail metrics / manifest。 |

Step2 正式成果以 GPKG/CSV 为稳定载体；JSON feature dump 只作为本地调试和兼容产物。内网脚本默认 `write_json_outputs=false`，避免在大规模写出阶段重复序列化大几何导致长时间无进度或进程被终止；summary 必须记录该开关，Step3 必须能消费同目录 GPKG replacement plan。
Step3 正式成果同样以 GPKG/CSV 为稳定载体；标准 CLI 默认 `suppress_feature_json_outputs=true`，不写出逐 feature 几何 JSON。需要本地调试旧 JSON feature dump 时，调用方必须显式关闭该开关。

## 7. 关键业务步骤

| 步骤 | 业务说明 |
|---|---|
| Step1 eligibility | 解析 `pair_nodes + junc_nodes`，先排除 `pair_nodes` 两端相同的非替换主通道，再基于 T04 `final_swsd_nodes` 中的 `has_evd / is_anchor` 识别候选与 final fusion units；T05 audit 中可消费的 `T11_MANUAL` 人工正向 relation 可释放对应 `fail3/fail4` anchor gate，也可释放人工确认的 `has_evd=no / missing` no-evidence relation。 |
| Step2 relation mapping | 用 T05 relation 映射 pair nodes 和 required junction nodes；被明确 detached / exempt 的 junc 只做审计和受控约束。 |
| Step2 buffer candidate | 以 SWSD Segment 50m buffer 筛选 RCSDRoad/RCSDNode 候选。 |
| Step2 corridor 构建 | 基于 pair nodes + required junction nodes 构建可解释 corridor 子图，不直接发布连通分量。 |
| Step2 pruning / hard audit | 裁剪 out seeds，检查叶子端点、双向 / 单向可达、required junction 相对拓扑、有效 buffer 穿行和窄通道视觉连续性。 |
| 高等级受限重审 | 对 `0-0* / 0-1*` Segment 的裁剪窗口不足失败，在原始 pair relation 不变时执行受限重审；single 以 RCSD 有向图联通 pair 路口并经过 50m buffer core，dual 优先 adaptive 到 125m，仍失败时可执行 dual graph-first 双向联通，但仍必须满足 required junction 相对拓扑和有效 buffer 穿行。 |
| 特殊组门控 | 环岛和复杂路口关联 Segment 支持局部替换；已通过硬审计的关联 Segment 保留在 replaceable，未通过的关联 Segment 保留 SWSD carrier。只有全组可替换时才发布特殊组内部 RCSD Road/Node；局部环岛必须保留 SWSD 环岛内部 road，不引入 RCSD 环岛内部端点间 road。 |
| Step2 replacement plan | 把标准 replaceable、特殊组内部对象、path-corridor group replacement 统一发布为 Step3 执行计划。 |
| Step2 problem registry | 将 rejected、当前 plan 覆盖和 Step2 自动解决的问题登记为可回流上游模块的审计记录。 |
| Step2 progress diagnostics | 在 `progress=True` 的长耗时运行中持续写出 heartbeat、阶段进度、group_audit 组级进度、逐个输出文件的 start/end/skipped、慢 Segment / 慢 group 记录和可触发栈转储，保证正式成果落盘阶段也能定位 I/O 或序列化卡点。 |
| Step3 替换 | 按 replacement plan 删除被替换 SWSDRoad 和端点 Node，引入 retained RCSDRoad/RCSDNode；若 Step1 detached junc 仍触达原 SWSDRoad，则以 `source=2` 保留为局部 restriction carrier，并重建语义路口 C。 |
| Step3 后处理 | 对提前右转、缺失端点、保留 SWSD carrier、path-corridor 局部 coverage 回退、surface-assisted node closure 和最终 topology connectivity 做审计或受控补齐，提升 F-RCSD 下游可用性；是否因准确 Relation 释放 retained-junction 20m gate 应在 Step2 plan 中完成。 |

## 8. 什么是对

- Step2 只接受 `status=0 / base_id>0` 的 T05 relation。
- Step1 final fusion units 只包含 `pair_nodes` 两端不同的 SWSD Segment；T01 `oneway_single_road_fallback` 生成的同一语义路口内部 self-pair fallback 必须进入 Step1 rejected 审计，不进入 Step2 替换分母。高等级 `0-0* / 0-1*` Segment 中，`has_evd=yes` 且 `is_anchor` 明确不可用的 `pair_nodes.kind_2=2048`、`junc_nodes.kind_2 in {16,2048}` 可被放行到 Step2 probe；`sgrade=0-2双` 且两个 `pair_nodes.kind_2` 均为 `2048` 的虚拟 T 型 pair 也可仅对 pair 主通道放行到 Step2 probe。T11 人工正向 relation 可释放对应 `fail3/fail4` anchor gate，也可释放 `has_evd=no / missing` 的人工确认 no-evidence relation；`is_anchor=no/fail1/fail2` 仍不放行。上述放行都不被视为 anchor 成功，不回写 T05 relation。
- `pair_nodes` 和未被明确 detached / exempt 的 `junc_nodes` 都是 hard required relation / topology 对象；detached / exempt junc 只做风险审计和局部 carrier 处理。
- retained RCSD graph 的叶子端点只能是 pair 对应 RCSD semantic nodes。
- 单向 Segment 的 source/target 只能由 SWSDRoad directed graph 推导。若 Segment 物理端点落在 `kind_2 in {64,128}` 特殊语义路口的 subnode 上，不能把 `mainnodeid` 折叠后的 pair 顺序当成唯一方向事实；初始 RCSD 有向 corridor 失败时，不能翻转 Segment 方向，只允许在原方向本地 corridor 存在、且方向缺口全部落在 `formway & 128 != 0` 的短 connector / 提前右转 Road 上时受限释放。
- 高等级受限重审不能修改 T05 pair anchor，且通过后必须记录 `adaptive_buffer_status / adaptive_buffer_distance_m / adaptive_buffer_source_reason`；single 的 `adaptive_buffer_source_reason` 以 `single_graph_first_longitudinal_retry:` 前缀标识。
- buffer-only probe 若给出非 ambiguous、非人工复核的 `high_confidence_pair_anchor_candidate`，即使 T05 两端已有 anchor 但一端或两端被诊断为 `candidate_anchor_mismatch`，或 T05 两端 pair relation 均缺失但候选 pair 满足高置信安全门槛，也只允许在 T06 当前 Segment 内构造候选 effective relation 并重新执行正式 extractor；重试失败仍保持 rejected，不回写 T05 relation。
- 单向 `multi_anchor_ambiguous` 只能在 probe 高置信、oriented RCSD pair 与 SWSD Segment 轴向端点侧位一致、且正式试算恰好一个 oriented candidate 通过时自动替换；多个候选通过、无候选通过或硬审计失败必须保持 rejected / 人工复核。
- Step3 只执行 Step2 replacement plan，不重新判定特殊组或 path-corridor group 可替换性；特殊组 `partial` 时只执行标准 / path-corridor ready action，不引入特殊组内部 RCSD Road/Node，保留未替换 SWSD carrier 并通过 T05 语义路口组表达端点关系。若标准 replaceable 的 final junc 集合相对 T01 原始 Segment 发生 detached junc 缩减，detached junc 触达的原 SWSDRoad 必须保留为 `source=2` 局部 carrier，并在 relation 中标记 `replaced+retained_swsd`。
- Step3 relation 中的 `frcsd_road_ids` 表达该 Segment 在最终 F-RCSD 中实际可消费的 carrier。`relation_status=replaced` 时应为正式 RCSD 替换道路；`retained_swsd / replaced+retained_swsd` 时可包含 `source=2` 的保留 SWSD carrier，但必须通过 `source_mix / frcsd_road_source_values`、状态和风险标记暴露来源。
- Step3 若在执行后发现 ready plan 的局部 coverage / topology 兜底无法形成安全 RCSD 替换，不得丢弃该 SWSD Segment；必须保留原 SWSD Road/Node 为 `source=2` carrier，或将混合关系标记为 `replaced+retained_swsd` 并进入 topology / risk audit。
- `replaced+retained_swsd` 可以保留原 SWSD carrier 以维持局部通行限制语义，但保留 carrier 的 endpoint 若已有 `swsd_to_frcsd_node_map` 指向 RCSD endpoint，最终 F-RCSD 中必须通过 `mainnodeid` 闭合到映射 RCSD mainnode/root；`semantic_junction_group_id` 只表达语义分组，不能替代 endpoint topology closure。
- Surface-assisted closure materialize 出的 split road 必须同步回所有引用原始 road id 的非 `retained_swsd` relation；`frcsd_road_ids` 不得保留已被替换掉的 pre-split road id。
- Surface-assisted closure 只在唯一候选、T04 未 reject、Patch 无冲突、距离和 source 条件可解释时补节点语义或 relation node map；它不能新增替换道路，不能修改原始道路几何。
- Step2 replacement plan 对 retained-junction 20m 距离 gate 的判断必须优先消费 T05 `status=0 / base_id>0` relation：若触发超距节点的 T05 base 与 plan 中 RCSD node canonical 后一致，则不得 hard block，必须保持 `plan_status=ready`，追加 `junction_alignment_to_retained_swsd_exceeds_topology_gate / junction_alignment_t05_relation_release / manual_review_required` 风险标记，并交由 Step3 最终 topology audit 闭合验证。Step3 surface-aware retained-junction gate 释放仅作为旧 plan 或缺少 Step2 relation-backed release 的兼容兜底；释放后仍必须重跑 topology audit，新增不可降级 hard fail 必须回退并显式暴露。
- T05 `intersection_match_all.geojson` 中 `status=0 / base_id>0` 的关系是 T06 语义路口组的业务证据；`many_target_to_one_base` 按 T05 非阻断审计口径允许形成同一 `semantic_junction_group_id`。分歧、合流等工艺差异导致的远距离 SWSD/RCSD node 不设硬距离阈值，但必须进入 `t06_step3_semantic_junction_groups.*` 和 topology warn 审计。
- T06 输出必须同时能解释“为什么能替换”和“为什么没有替换”：replacement plan 是执行边界，problem registry 是回流边界，topology audit 是最终 QA 边界。

## 9. 什么是错

- 用 buffer 连通分量直接作为 RCSDSegment。
- 未满足高置信安全门槛时，用 repair candidate 覆盖 T05 relation 并继续生成 replaceable。
- 将 `candidate_anchor_mismatch` 直接视为 T05 relation 修正并绕过 Step2 buffer / direction / geometry / 叶子端点 / 特殊组硬审计。
- 用高等级受限重审绕过 direction、有效 buffer 穿行、叶子端点、required junction 相对拓扑或特殊组硬审计。
- 用 `pair_nodes` 字段顺序或 `segmentid A_B` 顺序推断单向 direction。
- 在特殊语义路口 subnode 端点场景中，只按 `mainnodeid` 折叠后的语义节点方向判定单向 corridor，而不复核 Segment 内物理端点方向。
- 绕过 Step2 replacement plan 对 rejected Segment 执行 Step3 替换。
- 将 detached junc 的 `identity_retained_swsd` node map 解释成 RCSD 锚定成功，或因此回写 T05 relation。
- 因 SWSD/RCSD 原始 `id` 冲突而重写 ID；应依赖 `source` 区分并输出 collision audit。
- 在未通过 `relation_status / frcsd_road_source_values / source_mix` 区分来源的情况下，把保留 SWSD carrier 或 topology supplement 当成正式 RCSD 替换道路。
- 对 `replaced+retained_swsd` 的保留 SWSD carrier 只写 `semantic_junction_group_id`，但未把 endpoint `mainnodeid` 闭合到已映射 RCSD endpoint，就把 topology connectivity 记为 pass。
- 用 surface evidence 绕过 T04 reject、多 RCSD 候选、Patch 冲突或 Step2 可替换性判定；或在 surface-aware gate 释放后忽略无法由 T05 语义路口组解释的新增 topology hard fail。
- 因宽 buffer 审计通过就忽略窄通道主线断裂风险。

## 10. 当前治理缺口

- 架构目录已收敛为模块级 01-06 主结构，后续新增说明应优先落入 `03-solution-strategy.md`、`04-evidence-and-audit.md` 或 `06-risks-and-technical-debt.md`。
- Step3 输出的 SWSD-FRCSD Segment relation 需持续与 T09 输入契约保持同步。
- Step3 topology audit、surface topology audit 与 T10 visual check 已形成多类质量证据，后续需要沉淀为稳定的批量质量看板和上游任务分流口径。
