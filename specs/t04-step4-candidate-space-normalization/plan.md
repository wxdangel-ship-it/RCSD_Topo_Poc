# T04 Step4 Candidate-Space Normalization Plan

## 1. 实现目标

- 以最小改动把 Step4 candidate space 对齐到当前正式业务语义。
- 保持 current Step4 first-pass / final-tuning 主链路不回退。
- 不重写 branch-first 引擎，不改 Step4 final resolver，不改正向 RCSD 主链路。

## 2. 主要改动面

### 2.1 文档面

- `INTERFACE_CONTRACT.md §3.4 / §3.5`
  - 写入 `200m`
  - 写入“先定方向，再单向扫描”
  - 写入 explicit stop reason
  - 写入 geometry-level intrusion gate
  - 写入 degraded severity
- `architecture/04-solution-strategy.md`
  - 只保留 candidate-space normalization 的设计理由与互引
- `architecture/06-step34-repair-design.md`
  - 同步最小设计展开

### 2.2 代码面

- `_runtime_step4_geometry_core.py`
  - 新增 `PAIR_LOCAL_BRANCH_MAX_LENGTH_M = 200.0`
- `_runtime_step4_geometry_reference.py`
  - 新增 pair-local slice 诊断 helper
  - 输出 `seg_len_m / stop_reason / intruding_road_ids`
- `_event_interpretation_core.py`
  - 把双向择优改为“正向正式扫描 + reverse fallback”
  - 接入 200m 硬上限
  - 聚合 separation 指标与 stop reason
  - 接入 intrusion gate
  - 生成 degraded severity / fallback used
- `variant_ranking.py`
  - 将 hard degraded / intrusion 计入 variant penalty
- `case_models.py` / `outputs.py`
  - 透传新增 candidate-space 审计字段

## 3. 五个必改项

### 3.1 200m 对齐

- 候选空间 continuation / scan 统一改用 `PAIR_LOCAL_BRANCH_MAX_LENGTH_M = 200.0`。
- 移除 `patch_size_m * 0.45` 对 pair-local 正式延伸的隐式压制。

### 3.2 单向扫描

- 复用已有 `event_axis_branch -> scan_axis_unit_vector` 正式方向推导。
- `pair_local` 正式主逻辑只沿正向扫描。
- reverse 只在 `forward` 除 `0.0` 外没有有效 slice 时作为 fallback / audit。

### 3.3 separation 指标与 stop reason

- 每个有效 slice 记录 separation。
- 聚合输出：
  - `branch_separation_mean_m`
  - `branch_separation_max_m`
  - `branch_separation_consecutive_exceed_count`
  - `branch_separation_stop_triggered`
  - `stop_reason`
- 当前全局硬阈值未冻结；本轮先把指标化与审计化打通。

### 3.4 geometry-level intrusion gate

- 对当前 `between-branches segment` 做几何 intrusion 检查。
- 排除 boundary pair road memberships 与合法 axis/event branch roads。
- 命中时：
  - 当前延伸停止
  - 记录 `intruding_road_ids`
  - 必要时将当前 variant 记为 hard degraded

### 3.5 degraded severity

- 统一生成：
  - `degraded_scope_reason`
  - `degraded_scope_severity`
  - `degraded_scope_fallback_used`
- `hard` degraded 可驱动 `STEP4_FAIL`。

## 4. baseline-safe 策略

- 不改 `event_interpretation_branch_variants.py` 的 branch variant 主机制，避免牵动 `boundary_pair_signature`。
- 200m 只作用于 candidate-space materialization，不改 branch membership 本体。
- 不动 Step4 final resolver 和 RCSD claim reconcile。
- 所有 real-case frozen compare 默认以 accepted `8 case / 13 unit` 为主闸门。

## 5. 验证方案

- `pytest tests/modules/t04_divmerge_virtual_polygon -q -s`
- frozen real-case accepted batch compare
- `selected_candidate_region / boundary_branch_ids / valid_scan_offsets_m / selected_evidence / review_state` compare
- review flat / summary / JSON / CSV compare

## 6. 风险控制

- `_event_interpretation_core.py` 当前约 `79KB`，只做必要增量。
- 几何 stop/intrusion 逻辑尽量下沉到 `_runtime_step4_geometry_reference.py`。
- hard degraded 分类只覆盖“候选空间语义实质丢失”的组合，避免把既有 `STEP4_REVIEW` 误升成 `STEP4_FAIL`。
