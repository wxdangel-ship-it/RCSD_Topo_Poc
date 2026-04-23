# T04 Step4 Candidate-Space Normalization Spec

## 1. 本轮目标与边界

- 本轮只做 `Step4 candidate-space normalization`。
- 本轮保持 `branch-first + slice-fill` 主机制，不重写为新的 corridor builder。
- 本轮不进入 `Step5-7`。
- 本轮不重做主证据发现，不重做正向 RCSD 主链路，不重做 Step4 final conflict resolver。
- 本轮必须保持当前已通过的 Step4 final tuning baseline，不允许 silent regression。

## 2. 候选空间正式语义

### 2.1 候选空间本体

- 一个 event unit 的候选空间由当前有序边界 branch pair `(L, R)` 及其合法 continuation 物化。
- 候选空间以当前 representative node 为锚点起算。
- 候选空间容器继续采用：
  - `branch-first`
  - `slice-fill`
  - `unit-local branch pair region`
  - `unit-local structure face`
- 本轮不改成新的 corridor builder。

### 2.2 branch continuation 语义

- branch 可以跨 same-case sibling internal node 延续。
- branch 可以延续到非当前路口 node。
- continuation 的目的是维持当前 unit 的 `pair-middle` 连续语义，而不是回到 case 级大走廊。
- Step4 branch continuation 的正式硬上限冻结为 `200m`。

### 2.3 方向语义

- 候选空间正式方向必须先确定，再扫描。
- 当前 `(L, R)` 的正式候选空间只能沿合法单向延伸推进。
- reverse 可以保留，但只能作为 debug / fallback，不承担正式方向决策。

### 2.4 stop condition 语义

- Step4 pair-local 候选空间必须显式输出停止原因。
- 当前正式 stop reason 集至少包括：
  - `max_branch_length_reached`
  - `semantic_boundary_reached`
  - `pair_relation_replaced`
  - `branch_separation_too_large`
  - `road_intrusion_between_branches`
  - `pair_local_middle_missing`

### 2.5 road intrusion 语义

- `L / R` 之间不能夹其他 road 不能只靠角度 interval 近似表达。
- 本轮必须补成几何级 gate。
- 几何 gate 的命中结果必须留痕，至少输出 `intruding_road_ids`。

### 2.6 degraded scope 语义

- `degraded_scope_reason` 必须显式补 `severity`。
- 本轮至少区分：
  - `soft`
  - `hard`
- `hard` 级 degraded 组合允许升 `STEP4_FAIL`。
- 不能继续把“丢失候选空间语义”的严重退化永远只落在 `STEP4_REVIEW`。

## 3. 冻结与未冻结项

### 3.1 已冻结

- `PAIR_LOCAL_BRANCH_MAX_LENGTH_M = 200.0`
- `先定方向，再单向扫描`
- `stop_reason` 必须显式化
- `road intrusion` 必须是几何级 gate
- `degraded_scope` 必须带 severity

### 3.2 尚未冻结

- `PAIR_LOCAL_BRANCH_SEPARATION_MAX_M` 的最终全局硬阈值

### 3.3 本轮处理方式

- 本轮先把 separation 指标与 stop reason 接入实现与输出。
- 当前必须至少输出：
  - `branch_separation_mean_m`
  - `branch_separation_max_m`
  - `branch_separation_consecutive_exceed_count`
  - `branch_separation_stop_triggered`
  - `stop_reason`
- 在没有新的业务拍板前，不发明最终全局 separation 硬阈值。

## 4. baseline guard

- `Anchor_2` accepted baseline 仍是本轮回归主闸门。
- 正式 accepted gate 仍按 `8 case / 13 unit` 执行。
- 至少重点核查：
  - `760213`
  - `785671`
  - `857993`
  - `987998`
  - `17943587`
  - `30434673`
  - `73462878`
- frozen case 的 guard 重点包括：
  - `boundary_branch_ids` 不漂移
  - `selected_candidate_region` 容器语义不漂移
  - `selected_evidence / fact_reference_point / positive RCSD` 不回退
  - review/JSON/CSV/summary 不出现 silent drift

## 5. source-of-truth 收口

- 候选空间正式规则以 `INTERFACE_CONTRACT.md §3.4 / §3.5` 为主。
- `architecture/04-solution-strategy.md` 只保留“为什么”和策略说明，不再平行重述完整规则。
- `architecture/06-step34-repair-design.md` 只保留设计展开，不承担正式契约主文。
