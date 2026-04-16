# requirement_freeze_candidate

## 1. allowed space 正向构成
- allowed space 不能再被定义为整片 patch DriveZone union。
- 候选正向构成应只包含：语义路口核心区、own-group / must-cover 的必要覆盖区、selected mouth / handoff 的局部必要区、沿 trunk 到 frontier 为止的必要 corridor。

## 2. trunk frontier / stop condition
- Step3 必须显式输出 frontier 或 stop，不能只隐含在后续 polygon 行为中。
- single_sided_t_mouth 候选：min(DriveZone_edge_along_trunk, farthest_required_support_projection + buffer_m)。
- center_junction 候选：min(first_neighboring_semantic_junction_distance * alpha, DriveZone_edge_along_direction, farthest_required_support_projection + buffer_m)。
- alpha / buffer_m 在本轮只作为 shadow 参数，不写死进正式逻辑。

## 3. mouth / handoff 完成后的停止规则
- 当 trunk 继续延伸但不再新增 own-group / required RC / selected mouth 的必要覆盖时，Step3 必须停止。
- 不能把后续也许还能补出更大 polygon 当成继续放行理由。

## 4. RCSD 缺失 / 表达差异时的独立 stop condition
- 即使 RCSD 缺失、表达差异或约束不足，Step3 仍必须给出独立 stop condition。
- 如果当前无法可靠解出 frontier，只允许显式回退到 baseline，并输出 step3_shadow_frontier_unresolved=true 与 unresolved reason。
- 禁止 silent fallback 到整片 DriveZone。
