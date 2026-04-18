# T03 - INTERFACE_CONTRACT

## 定位

- 本文件是 `t03_virtual_junction_anchor` 的稳定契约面。
- 当前正式范围为：冻结 `Step3 legal-space baseline` 之上的 `Step4-5` 联合阶段。
- `Step3` 仍是前置层，不在本轮被重新定义或回写。
- 当前正式模板只包括 `center_junction` 与 `single_sided_t_mouth`。
- 模块目标、上下文与构件关系以 `architecture/*` 为准。

## 1. 目标与范围

- 模块 ID：`t03_virtual_junction_anchor`
- 目标：
  - 以 Anchor61 `case-package` 与冻结 Step3 run root 为正式输入
  - 输出供 `Step6` 消费的 `required / support / excluded` RCSD 干净中间结果包
  - 保持单 case / batch / 平铺 PNG / summary / index 稳定可回读
- 当前正式范围：
  - `case-package` loader / preflight
  - `Step1` 最小上下文组装
  - `Step2` 模板归类
  - 读取冻结 `Step3 allowed space / status / audit`
  - `Step4 = RCSD 关联语义识别`
  - `Step5 = foreign 过滤与排除落地`
  - 批量运行、平铺 PNG、CSV/JSON 汇总
- 明确不在正式范围：
  - `diverge / merge / continuous divmerge / complex 128`
  - `T02` 独立 `stage4 div/merge`
  - 在 `Step4-5` 中重新定义 `allowed space / corridor / 50m fallback`
  - polygon 最终面
  - `Step6` 业务规则

## 2. Inputs

### 2.1 必选输入

- Anchor61 `case-package` 根目录
- 冻结 Step3 run root
- 每个 case 必须包含：
  - `manifest.json`
  - `size_report.json`
  - `drivezone.gpkg`
  - `nodes.gpkg`
  - `roads.gpkg`
  - `rcsdroad.gpkg`
  - `rcsdnode.gpkg`

### 2.2 Step3 冻结前置输入

- 对应 case 的：
  - `step3_allowed_space.gpkg`
  - `step3_status.json`
  - `step3_audit.json`
- 当前实现的官方默认 `--step3-root` 指向仓库内现行 Step3 正式基线 run root；显式单 case 调试可改写为其它包含 Step3 产物的 run root。
- `Step4-5` 对冻结 Step3 的关键 prerequisite 采用显式校验：
  - `step3_status.json` 必须提供 `step3_state`
  - `step3_status.json` 必须直接提供非空 `selected_road_ids`
  - 不允许在 `selected_road_ids` 缺失时静默回退到 `Step1 target_road_ids`
  - prerequisite 缺失时，case 进入 `step45_state = not_established`，并在 status/audit 中显式记录 blocker 与 issue 列表

### 2.3 输入前提

- 所有空间处理统一到 `EPSG:3857`
- `nodes` 至少需具备：
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
- `rcsdnode` 至少需具备：
  - `id`
  - `mainnodeid`
- `kind_2` 只支持：
  - `4 -> center_junction`
  - `2048 -> single_sided_t_mouth`

## 3. Outputs

### 3.1 run root 固定输出

- `preflight.json`
- `summary.json`
- `step45_review_index.csv`
- `step45_review_flat/`
- `cases/`

### 3.2 单 case 固定输出

- `step45_required_rcsdnode.gpkg`
- `step45_required_rcsdroad.gpkg`
- `step45_support_rcsdnode.gpkg`
- `step45_support_rcsdroad.gpkg`
- `step45_excluded_rcsdnode.gpkg`
- `step45_excluded_rcsdroad.gpkg`
- `step45_required_hook_zone.gpkg`
- `step45_foreign_swsd_context.gpkg`
- `step45_foreign_rcsd_context.gpkg`
- `step45_status.json`
- `step45_audit.json`
- `step45_review.png`

### 3.3 状态与说明

- `step45_state` 只允许：
  - `established`
  - `review`
  - `not_established`
- `association_class` 只允许：
  - `A`
  - `B`
  - `C`
- `A/B/C` 定义：
  - `A`：RCSD 也构成当前 case 的语义路口关联集
  - `B`：RCSD 不构成完整语义路口，但存在相关 `RCSDRoad`，重点输出 hook zone；当前正式口径下统一映射为 `review`，等待 `Step6` 再收窄
  - `C`：无相关 `RCSDRoad`
- `step45_status.json` 至少包含：
  - `case_id / template_class / association_class / step45_state / step45_established / reason / key_metrics`
  - `step3_state`
  - `selected_road_ids`
  - `association_executed / association_reason / association_blocker`
  - `step45_prerequisite_issues`
  - `required_rcsdnode_ids / required_rcsdroad_ids`
  - `support_rcsdnode_ids / support_rcsdroad_ids`
  - `excluded_rcsdnode_ids / excluded_rcsdroad_ids`
  - `rcsd_semantic_core_missing`
  - `nonsemantic_connector_rcsdnode_ids / true_foreign_rcsdnode_ids`
- `step45_audit.json` 至少包含：
  - `step3_prerequisite`
  - `step4`
  - `step5`
  - `joint_phase`
- 当门禁失败导致 `Step4` 未执行时：
  - `association_class` 仍收敛到契约枚举 `A / B / C`，当前实现使用保守占位 `C`
  - 真实阻断原因通过 `association_blocker` 与 `step45_prerequisite_issues` 表达
  - 不再输出 `association_class = unsupported / blocked`

### 3.4 RCSD 节点语义约束

- `step45_support_only` 不是算法异常，而是当前联合阶段的正式保守策略：
  - 当 RCSD 下只有 support / hook zone，没有稳定语义路口 core 时，状态保持 `association_class = B / step45_state = review`
  - `step45_status.json` 与 `step45_audit.json` 必须显式写出 `rcsd_semantic_core_missing = true`
- `degree = 2` 的 `RCSDNode` 只视为 connector，不进入 `required semantic core`
- `degree = 2` connector node 与真正 foreign node 必须在审计上分开记录：
  - `nonsemantic_connector_rcsdnode_ids`
  - `true_foreign_rcsdnode_ids`
- 对 `single_sided_t_mouth`，若 `support RCSDRoad` 在当前竖向退出链附近出现平行重复，不按“离 semantic core 更近”处理，而按“更贴近竖方向退出当前面一侧”保留一条：
  - 审计字段：`parallel_support_duplicate_dropped_rcsdroad_ids`

## 4. EntryPoints

### 4.1 官方入口

```bash
python3 -m rcsd_topo_poc t03-step45-rcsd-association --help
```

### 4.2 冻结前置入口

```bash
python3 -m rcsd_topo_poc t03-step3-legal-space --help
```

## 5. Params

### 5.1 关键参数类别

- 输入与选择：`case-root / step3-root / case-id / max-cases`
- 执行控制：`workers / run-id / debug / debug-render`
- 输出控制：`out-root`

### 5.2 参数原则

- `Step4-5` 只暴露批处理所需的稳定参数。
- `debug-render` 只控制调试标注，不影响业务结果与强制输出的 `step45_review.png`。
- 不暴露用于重写 Step3 规则的参数。

## 6. Current SWSD Surface Filter

- 每个 case 的 `Step4-5` 只处理“当前 SWSD 路口所在道路面”。
- 当前 SWSD 道路面由 `Step3 selected_road_ids` 在 `drivezone` 内构成的局部道路面近似得到。
- 其余道路面上的 SWSD roads / foreign groups 不参与当前 case 的全局处理，也不进入 `foreign_swsd_context`。
- 不落在当前 SWSD 道路面上的 `RCSDNode / RCSDRoad` 不参与当前 case 的全局处理，不进入 `required / support / excluded / foreign` 主结果集合。
- 审计中必须区分：
  - `active_rcsdnode_ids / active_rcsdroad_ids`
  - `ignored_outside_current_swsd_surface_rcsdnode_ids / ignored_outside_current_swsd_surface_rcsdroad_ids`

## 7. Acceptance

1. Anchor61 原始总量固定为 `61` 个 case，可批量运行
2. 默认正式全量验收集固定排除 `922217 / 54265667 / 502058682`，按剩余 `58` 个 case 统计；显式 `--case-id` 仍可单独复跑它们
3. 每个进入全量验收集的 case 固定 `12` 个业务输出齐全
4. `step45_review_flat/` 的 PNG 数量应与默认正式全量验收集规模一致，当前口径为 `58`
5. `step45_state` 仅出现 `established / review / not_established`
6. `summary.json` 与 `preflight.json` 必须能直接表达：
  - `raw_case_count = 61`
  - `default_formal_case_count = 58`
  - `excluded_case_ids`
  - `effective_case_ids`
  - `missing_case_ids`
  - `failed_case_ids`
7. 单 case 交付是供 `Step6` 消费的干净中间结果包，不是 polygon
