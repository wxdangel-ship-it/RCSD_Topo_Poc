# T03 - INTERFACE_CONTRACT

## 定位

- 本文件是 `t03_virtual_junction_anchor` 的稳定契约面。
- 当前正式范围仅限 `Phase A / Step3 legal-space baseline only`。
- 本轮已进入 `Step3` 修复轮，契约仍以 `A-H` 为正式规则范围，不扩到 `Step4-7`。
- 模块目标、上下文与构件关系以 `architecture/*` 为准。
- `README.md` 只承担操作者入口职责。
- 线程 `REQUIREMENT.md` 本轮整体不启用，不作为当前模块事实源。

## 1. 目标与范围

- 模块 ID：`t03_virtual_junction_anchor`
- 目标：
  - 以 Anchor61 `case-package` 为正式输入，独立实现最小 `Step1/Step2` 支撑与 `Step3 legal space`
  - 交付批量运行、case 级产物、平铺 PNG 审查目录与索引汇总
- 当前正式范围：
  - `case-package` loader / preflight
  - `Step1` 最小上下文组装
  - `Step2` 模板归类
  - `Step3` A-H、allowed space、三类 negative mask、`step3_state`
  - 批量运行、平铺 PNG、CSV/JSON 汇总
- `input_gate_failed` 仅作为前置输入门禁 `reason`，不新增第四种 `step3_state`，也不代表 Step3 业务失败态本身
- 已确认的 input-gate hard-stop case `922217 / 54265667 / 502058682` 需要记录为 T03 默认全量验收排除集：后续默认全量跑批不再计入这些 case，但显式点名单 case 调试仍允许单独运行
- `Rule D` 的最终 `allowed space` 必须满足 `DriveZone` containment；当不存在更早的稳定边界时，`50m fallback` 允许作为可成立路径，不自动进入 `review`，只保留审计信息
- `Rule A` 只允许截断“当前语义路口分支上真正进入相邻语义路口的入口”；若候选截断会覆盖当前 target group core，则该截断无效
- `Rule B` 只允许针对与当前语义路口真正无关的 `foreign road / arm / node` 生成负向掩膜；当前语义路口 branch、直接关联 road 及其二度衔接 road 不得因为“未进入 frontier”而被回灌判成 foreign
- `Rule D` 在当前语义路口关联 branch 上必须同时支持进入路口与退出路口的双向追溯，直到下一个或上一个语义路口为止
- `Rule A` 的负向边界应在与当前路口直接关联的相邻语义路口入口处，沿当前 branch 反向构造 `1m` 逆向掩膜；正向增长到这里应自然终止，不再依赖路口前横截切面
- `Rule E` 当前只定义为 baseline partial；`lane_guard_status` 固定记录为 `proxy_only_not_modeled`，不得宣称已 fully complete
- `Rule E` 的 `single_sided_t_mouth` opposite 判定不得覆盖当前语义路口关联 road，也不得覆盖这些 road 的二度衔接 road；`RCSDRoad` 只允许作为 near-corridor proxy，挂靠到已识别的 opposite `SWSD road`，不得以 opposite side 全量 `RCSDRoad` 直接主导硬阻断；若某个 `RCSDRoad` proxy 仍稳定覆盖当前 branch 或 junction-related roads，则必须 suppress，不得 materialize 成 hard blocker
- 双 node `single_sided_t_mouth` 新增规则：
  - 当两 `node` 间存在 bridge 且 bridge 位于合法道路面内时，该 bridge 应进入 `allowed-space` 主通路，而不是单独降级到 review-only 分支
  - 当共享 `2进2出` 的 `node` 仅承担 through-node 角色时，不应中断主通路增长，也不得因共享 node 事实直接判成 opposite blocker
- 当前不在正式范围：
  - `Step4/5/6/7`
  - cleanup/trim 补救
  - stage4 聚合与 `complex 128`
  - 最终 topology / serialization 输出族

## 2. Inputs

### 2.1 必选输入

- Anchor61 `case-package` 根目录
- 每个 case 必须包含：
  - `manifest.json`
  - `size_report.json`
  - `drivezone.gpkg`
  - `nodes.gpkg`
  - `roads.gpkg`
  - `rcsdroad.gpkg`
  - `rcsdnode.gpkg`

### 2.2 输入前提

- 正式输入契约固定为 `nodes / roads / drivezone / rcsdroad / rcsdnode / manifest / mainnodeid(case_id)`。
- 所有空间处理统一到 `EPSG:3857`。
- `nodes` 代表节点至少需具备：
  - `id`
  - `mainnodeid`
  - `has_evd`
  - `is_anchor`
  - `kind_2`
  - `grade_2`
- `roads / rcsdroad` 至少需具备：
  - `id`
  - `snodeid`
  - `enodeid`
  - `direction`

## 3. Outputs

- run root 固定输出：
  - `preflight.json`
  - `summary.json`
  - `step3_review_index.csv`
  - `step3_review_flat/`
  - `cases/`
- 单 case 固定输出：
  - `step3_allowed_space.gpkg`
  - `step3_negative_mask_adjacent_junction.gpkg`
  - `step3_negative_mask_foreign_objects.gpkg`
  - `step3_negative_mask_foreign_mst.gpkg`
  - `step3_status.json`
  - `step3_audit.json`
  - `step3_review.png`

说明：

- `step3_status.json` 至少包含 `case_id / template_class / step3_state / step3_established / reason / key_metrics`
- `step3_status.json` 可额外携带 `input_gate_failed` 的门禁诊断信息，但不得据此扩展状态枚举
- `step3_audit.json` 至少包含 `rules.A-H / adjacent_junction_cuts / foreign_object_masks / foreign_mst_masks / growth_limits / cleanup_dependency / must_cover_result / blocked_directions / review_signals`
- 对 `Rule D / Rule E` 建议追加审计字段：
  - `rule_d_fallback_applied`
  - `rule_d_fallback_distance_m`
  - `rule_d_fallback_reason`
  - `lane_guard_status`
  - `double_node_bridge_in_allowed_space`
  - `through_node_shared_2in2out`
  - `through_node_break_suppressed`
- 平铺目录必须无子目录，文件名固定为 `<case_id>__<state>.png`

## 4. EntryPoints

### 4.1 官方入口

```bash
python3 -m rcsd_topo_poc t03-step3-legal-space --help
```

## 5. Params

### 5.1 关键参数类别

- 输入与选择：`case-root / case-id / max-cases`
- 执行控制：`workers / run-id / debug`
- 输出控制：`out-root`

### 5.2 参数原则

- 本模块当前只暴露批处理所需的稳定参数。
- 不暴露 `cleanup / trim / review_mode / Step4-7` 类参数。

## 6. Acceptance

1. Anchor61 原始 Anchor 总量固定为 `61` 个 case，可批量运行
2. 默认正式全量验收集固定排除 `922217 / 54265667 / 502058682` 这 `3` 个 input-gate hard-stop case，正式全量统计口径按剩余 `58` 个 case 计算；显式 `--case-id` 仍可单独复跑它们
3. 每个进入全量验收集的 case 固定 `7` 个业务输出齐全
4. `step3_review_flat/` 的 PNG 数量应与默认全量验收集规模一致，当前口径为 `58`
5. `step3_state` 仅出现 `established / review / not_established`
6. 未引入 `Step4/5/6/7` 或 cleanup/trim 作为 `Step3` 主通路
