# 05 质量要求

## 1. 替换正确性

- Step2 只接受 `status=0 / base_id>0` 的 T05 relation。
- T11 人工正向 relation 允许释放 T06 Step1 中 `is_anchor=fail3/fail4` 的旧锚定失败门禁，也允许释放人工确认的 `has_evd=no / missing` no-evidence relation；释放后仍必须通过 Step2 relation mapping、RCSD 连通性、方向性、buffer、视觉连续性和 Step3 topology audit，且不得释放 pair 合法性、`is_anchor=no/fail1/fail2`、非人工 relation 或 `graph_consumable=0`。
- `pair_nodes` 和未被明确 detached / exempt 的 `junc_nodes` 都是 hard required relation / topology 对象。
- buffer 连通分量不能直接作为 RCSDSegment，必须收缩为 pair nodes + required junction nodes 之间的可解释 corridor。
- `replaceable` 必须通过方向、叶子端点、required junction 相对拓扑、有效 buffer 穿行、视觉连续性和特殊组局部替换门控；RCSD 不要求完全留在 SWSD 50m buffer 内，只有 pair-to-pair 连续通路完全不经过 SWSD Segment buffer 时才硬拒绝。反向 buffer / coverage 差异写入 replacement plan 风险并追加 `manual_review_required`。
- 准确 T05 relation 下 retained-junction 20m 距离 gate 不能作为 hard reject，只能作为 Step2 replacement plan 风险标记并由 Step3 topology audit 验证。
- 最终 F-RCSD topology 发布门只使用 `final_frcsd_topology_fail_count`：SWSD Segment 通行关系在 final graph 中断裂或最终对象形成独立/单侧挂接时 hard fail；relation failed、coverage 和仅映射证据缺失不得混入正式最终错误数。
- hard-gate 直接回退后必须先用当前内存中的 F-RCSD 重建 topology，再判断是否存在 mixed-source 级联 fail；满足有效 T05 唯一 root、remaining replaced relation 唯一同 root、无 Patch/T04 冲突和 12m 距离门禁时，应先做 retained endpoint mainnode 收口，再决定第二轮 Segment 回退。不得用落盘旧 audit、相邻几何或直接失败节点扩大收口范围。
- Step3 只能执行 `t06_segment_replacement_plan.*` 中 `plan_status=ready` 的 action。

## 2. GIS 与拓扑要求

- SWSD geometry 定义 buffer window；RCSD geometry 用于候选选择和 retained 输出。
- `formway` 必须按 bit mask 判断，提前右转为 `formway & 128 != 0`。
- Step3 不重写 SWSD/RCSD 原始 id，通过 `source` 区分。
- F-RCSD Road 的端点必须存在于 F-RCSD Node。
- retained SWSD carrier、topology supplement 和提前右转补丁可作为最终可消费 carrier 暴露，但必须通过 `relation_status / frcsd_road_source_values / source_mix` 与风险标记区分来源，不得被正式 RCSD 来源审计当成 `source=1` 替换道路。
- surface-assisted closure 只能补节点语义或 relation node map，不能新增替换道路。

## 3. 业务边界质量

- 高置信 repair candidate 只允许在当前 Segment 内构造 effective relation 并重新跑 Step2 硬审计；不得回写 T05 relation。
- 高等级 graph-first / adaptive buffer 受限重审不能绕过方向、有效 buffer 穿行、叶子端点、required junction 相对拓扑或特殊组局部替换门控。
- `accepted_non_replaceable` 表示 T06 已确认不可替换且不应继续上游重跑的场景。

## 4. 回归要求

测试应覆盖 Step1 self-pair rejected、junc 脱挂、advance right bit mask、Step2 replacement plan / problem registry、pair anchor formal retry、特殊组 `passed / partial / blocked` 门控、Step3 replacement plan 优先、detached carrier 保留、advance right attachment、surface topology audit 和 topology connectivity audit。

## 5. 性能要求

Step2 全量运行需关注 buffer candidate graph、probe、group replacement 和输出写入体量。Step3 需关注 F-RCSD 输出、surface topology postprocess 和 topology connectivity audit 的耗时。性能优化不得改变 replacement plan、problem registry 或 Step3 relation 的业务语义。
