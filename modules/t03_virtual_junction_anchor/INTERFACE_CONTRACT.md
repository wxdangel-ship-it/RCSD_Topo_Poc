# T03 - INTERFACE_CONTRACT

## 定位

- 本文件是 `t03_virtual_junction_anchor` 的稳定契约面。
- 当前正式范围为：冻结 `Step3 legal-space baseline` 之上的 `Step4-7 clarified formal stage`。
- `Step3` 仍是前置层，不在本模块中被重新定义或回写。
- 当前正式模板只包括 `center_junction` 与 `single_sided_t_mouth`。
- 模块目标、上下文、closeout 与历史说明以 `architecture/*` 为准。

## 1. 目标与范围

- 模块 ID：`t03_virtual_junction_anchor`
- 目标：
  - 以 Anchor61 `case-package` 与冻结 Step3 run root 为正式输入
  - 输出 `Step45 required / support / excluded` RCSD 中间结果包
  - 输出 `Step67 accepted / rejected` 最终发布结果与审计包
  - 保持单 case / batch / 平铺 PNG / summary / index 稳定可回读
- 当前正式范围：
  - `case-package` loader / preflight
  - `Step1` 最小上下文组装
  - `Step2` 模板归类
  - 读取冻结 `Step3 allowed space / status / audit`
  - `Step4 = RCSD` 关联语义识别
  - `Step5 = foreign / excluded` 分类与审计
  - `Step6 =` 受约束几何建立与后处理
  - `Step7 = accepted / rejected` 最终业务发布
  - 批量运行、平铺 PNG、CSV/JSON 汇总
- 明确不在正式范围：
  - `diverge / merge / continuous divmerge / complex 128`
  - `T02` 独立 `stage4 div/merge`
  - 在 T03 中重新定义 `allowed space / corridor / 50m fallback`
  - 新增 `Step67` repo 官方 CLI
  - 将 `20m`、buffer 宽度、cover ratio 等 solver 参数冻结为长期业务契约

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
- `Step4-7` 对冻结 Step3 的关键 prerequisite 采用显式校验：
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

## 3. Stable Business Semantics

### 3.1 Step45 前置分类层

- `association_class` 只允许：
  - `A`
  - `B`
  - `C`
- `step45_state` 只允许：
  - `established`
  - `review`
  - `not_established`
- `A / B / C` 定义：
  - `A`：RCSD 也构成当前 case 的语义路口关联集
  - `B`：RCSD 不构成完整语义路口，但存在相关 `RCSDRoad / hook zone`
  - `C`：无相关 `RCSDRoad`
- `step45_support_only` 不是算法异常，而是稳定业务保守态：
  - 当 RCSD 下只有 support / hook zone，没有稳定语义路口 core 时，状态保持 `association_class = B / step45_state = review`
  - `Step6` 合法收敛后允许在 `Step7` 转为 `accepted`

### 3.2 当前 SWSD surface 过滤

- 每个 case 只处理“当前 SWSD 路口所在道路面”的 SWSD / RCSD 对象
- 道路面外对象不进入当前 case 主结果集合
- 审计中必须区分：
  - `active_rcsdnode_ids / active_rcsdroad_ids`
  - `ignored_outside_current_swsd_surface_rcsdnode_ids / ignored_outside_current_swsd_surface_rcsdroad_ids`

### 3.3 RCSD 调头口过滤

- 若某条 `RCSDRoad` 的两端分别关联到方向相反的 `RCSDRoad`，则该 `RCSDRoad` 视为 `调头口 RCSDRoad`
- `调头口 RCSDRoad` 在当前 case 的 `Step45` 语义处理中视为不存在：
  - 不进入后续 `candidate / required / support / excluded` 分类
  - 不得在 `Step6` 被重新解释为 `local required RC`
- 去除 `调头口 RCSDRoad` 后，后续 `degree = 2 connector` 识别与 `RCSDRoad chain merge` 必须基于过滤后的活动集重新计算
- 审计至少要稳定表达：
  - `active_rcsdroad_ids_before_u_turn_filter`
  - `u_turn_rcsdroad_ids`
  - `u_turn_rcsdroad_audit`

### 3.4 degree-2 connector 语义

- `degree = 2` 的 `RCSDNode` 只视为 connector，不进入 `required semantic core`
- connector node 与真正 foreign node 必须在审计上分开记录：
  - `nonsemantic_connector_rcsdnode_ids`
  - `true_foreign_rcsdnode_ids`
- 经 `degree = 2` connector 串接的 candidate `RCSDRoad`，必须先按同一 `RCSDRoad chain` 合并，再参与 `required / support / excluded` 分类
- 该 chain merge 当前不考虑角度门禁
- 审计至少要稳定表达：
  - `degree2_merged_rcsdroad_groups`

### 3.5 single_sided_t_mouth support 去重

- 对 `single_sided_t_mouth`，若 `support RCSDRoad` 在当前竖向退出链附近出现平行重复，按“更贴近竖方向退出当前面一侧”保留
- 审计字段：
  - `parallel_support_duplicate_dropped_rcsdroad_ids`

### 3.6 single_sided_t_mouth / association_class=A 横向口门规则

- 本规则只适用于：
  - `template_class = single_sided_t_mouth`
  - `association_class = A`
- 规则前提：
  - 必须先完成 `RCSD 调头口过滤`
  - 必须基于过滤后的活动集重算 `degree2 connector / chain merge / required-support-excluded`
- 竖向 tracing 起点：
  - 以 Step3 已冻结的 `single_sided` 竖方向候选空间为准
  - 在该竖方向候选空间内查找当前 case 的相关 `RCSDRoad / RCSDRoad chain`
  - 它们构成当前 `single_sided_t_mouth / A` 规则的 tracing seed
- tracing 过程：
  - 从竖方向 tracing seed 出发，沿过滤后的相关 `RCSDRoad / RCSDRoad chain` 向横方向追踪
  - tracing 过程中的 `RCSDRoad` 不要求整体完全落在当前候选空间内
  - 只要最终确认的 `RCSDNode` 落在横方向候选空间内，即可视为当前 tracing 有效
- RCSD 横向口门节点：
  - tracing 结果应在横方向候选空间内确认当前 case 对应的 `RCSD T-mouth` terminal `RCSDNode`
  - terminal `RCSDNode` 以 tracing 可达 `RCSDRoad / RCSDRoad chain` 的端点节点为准，不要求它本身进入 `required semantic core`
  - 正常形态下应形成横方向两侧一对 `RCSDNode`
  - 若 tracing 无法在横方向两侧都确认 terminal `RCSDNode`，则当前 `A` 类 `single_sided_t_mouth` 横向口门特化规则不成立，横方向回到 generic directional boundary
- 横方向边界锚点：
  - 对 tracing 已确认 terminal `RCSDNode` 的横方向 branch，以该 terminal `RCSDNode` 的外延位置为主锚点
  - 该主锚点在当前 branch 上向外扩 `5m`，形成当前侧横方向截断位置
  - 若主锚点外扩后仍未超过 generic `20m directional boundary`，则当前侧仍回到 generic `20m`
- stop rule：
  - 横方向 `5m` 扩展不得越过当前侧前方其他直接关联语义路口
  - 该 stop rule 同时适用于：
    - `RCSD` 直接关联语义路口
    - `SWSD` 直接关联语义路口
  - 若前方存在更近的直接关联语义路口，则必须在该处之前停止，不得越过
- 与 generic 规则的关系：
  - 横方向 `A` 类口门规则是 `single_sided_t_mouth` 的模板特化规则
  - 未被当前 tracing 明确认定为横向 terminal `RCSDNode` 的一侧，不得被同侧或对侧语义信号放宽
  - 未达到 `terminal RCSDNode + 5m > 20m` 的一侧，仍回到 generic directional boundary
- 与冻结 `Step3 two-node T bridge` 的关系：
  - 若冻结 `Step3` 已对当前 case 标记 `two_node_t_bridge_applied = true`，则 `Step67 directional boundary / polygon_seed` 必须继承该 bridge corridor
  - 该 bridge corridor 属于全局 target-connected center support，不得因横方向局部截断、sibling branch trim 或 cleanup 在中心位置被切断
  - 对这类 case，`Step67 accepted` 的几何至少不得表现为由横向口门截断引入的中心断开、多组件狭长残留或桥位空洞

### 3.7 Step6 业务边界

- `Step6` 是受约束几何建立层，不是结果导向补面层
- `Step6` 的硬优先级固定为：
  1. 不得突破 Step3 legal space
  2. 不得纳入 Step5 excluded / foreign hard negative mask
  3. 必须满足 Step1 semantic junction must-cover
  4. 必须满足条件性 `local required RC must-cover`
  5. 上述成立后才允许做几何优化
- `Step6` 必须先确定 directional boundary，再在该边界内构面：
  - 不允许先裁剪再把 `required RC` 整体补回边界外
  - final geometry 不得突破 directional boundary
- `required RC must-cover` 当前正式语义为：
  - 只对 directional boundary 内的 `local required RC` 成立
  - directional boundary 外的 `required RCSDRoad / RCSDNode` 不得作为 `Step6 accepted` 的硬失败条件
- 当前正式契约不冻结 Step6 solver 常量、阈值与具体构面参数

### 3.8 Step5 / Step6 foreign 语义

- `Step5` 负责 `required / support / excluded / audit-only foreign` 的分组与审计
- `Step5` 当前不再提供 hard polygon foreign context 作为 Step6 subtract 输入
- `Step6` 当前唯一正式 hard negative mask 来源为：
  - `excluded_rcsdroad_geometry -> road-like 1m mask`
- node 类 `excluded / foreign` 当前保留在审计层，不进入本轮 hard subtract
- `step45_foreign_swsd_context.gpkg / step45_foreign_rcsd_context.gpkg` 为兼容性审计产物，可以为空，不应再被解释为 hard negative polygon context

### 3.9 Step7 发布层

- `Step7` 只允许机器主状态：
  - `accepted`
  - `rejected`
- `Step7` 只基于冻结的 `Step1-6` 结果发布，不重新定义业务
- `V1-V5` 只属于视觉审计层，不等价于机器主状态
- 当前视觉审计类仍保留：
  - `V1 认可成功`
  - `V2 业务正确但几何待修`
  - `V3 漏包 required`
  - `V4 误包 foreign`
  - `V5 明确失败`

## 4. Outputs

### 4.1 Step45 run root 固定输出

- `preflight.json`
- `summary.json`
- `step45_review_index.csv`
- `step45_review_flat/`
- `cases/`

### 4.2 Step45 单 case 固定输出

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

### 4.3 Step45 status / audit 至少包含

- `step45_status.json` 至少包含：
  - `case_id / template_class / association_class / step45_state / step45_established / reason / key_metrics`
  - `step3_state`
  - `selected_road_ids`
  - `association_executed / association_reason / association_blocker`
  - `step45_prerequisite_issues`
  - `active_rcsdroad_ids_before_u_turn_filter`
  - `u_turn_rcsdroad_ids`
  - `required_rcsdnode_ids / required_rcsdroad_ids`
  - `support_rcsdnode_ids / support_rcsdroad_ids`
  - `excluded_rcsdnode_ids / excluded_rcsdroad_ids`
  - `rcsd_semantic_core_missing`
  - `nonsemantic_connector_rcsdnode_ids / true_foreign_rcsdnode_ids`
  - `degree2_merged_rcsdroad_groups`
  - `ignored_outside_current_swsd_surface_rcsdnode_ids / ignored_outside_current_swsd_surface_rcsdroad_ids`
  - `parallel_support_duplicate_dropped_rcsdroad_ids`
- `step45_audit.json` 至少包含：
  - `step3_prerequisite`
  - `step4`
  - `step5`
  - `joint_phase`

### 4.4 Step67 run root 固定输出

- `preflight.json`
- `summary.json`
- `step67_review_index.csv`
- `step67_review_accepted/`
- `step67_review_rejected/`
- `step67_review_v2_risk/`
- `step67_review_flat/`
- `cases/`

### 4.5 Step67 单 case 固定输出

- `step6_polygon_seed.gpkg`
- `step6_polygon_final.gpkg`
- `step6_constraint_foreign_mask.gpkg`
- `step67_final_polygon.gpkg`
- `step6_status.json`
- `step6_audit.json`
- `step7_status.json`
- `step7_audit.json`
- `step67_review.png`

### 4.6 Step67 status / audit 至少包含

- `step6_status.json` 至少要能区分：
  - `step6_state`
  - `geometry_established`
  - `reason`
  - `primary_root_cause / secondary_root_cause`
  - `semantic_junction_cover_ok`
  - `required_rc_cover_ok`
  - `within_legal_space_ok`
  - `within_direction_boundary_ok`
  - `foreign_exclusion_ok`
  - `required_rc_cover_mode`
  - `local_required_rcsdnode_ids / local_required_rcsdroad_ids`
  - `step3_two_node_t_bridge_inherited`
- `step7_status.json` 至少要包含：
  - `case_id / template_class / association_class`
  - `step45_state / step6_state / step7_state`
  - `accepted`
  - `reason`
  - `visual_review_class`
  - `visual_audit_family`
  - `manual_review_recommended`
  - `root_cause_layer / root_cause_type`
  - `note`
- `step67_review_index.csv` 至少要包含：
  - `sequence_no`
  - `case_id`
  - `template_class`
  - `association_class`
  - `step45_state`
  - `step6_state`
  - `step7_state`
  - `visual_class`
  - `reason`
  - `note`
  - `image_name`
  - `image_path`

## 5. EntryPoints

### 5.1 repo 官方入口

```bash
python3 -m rcsd_topo_poc t03-step45-rcsd-association --help
```

### 5.2 冻结前置入口

```bash
python3 -m rcsd_topo_poc t03-step3-legal-space --help
```

### 5.3 Step67 交付方式

- 当前 `Step67` 没有 repo 官方 CLI
- 当前正式 Step67 批量交付通过模块内 `run_t03_step67_batch()` 与 closeout run root 维持

## 6. Params

### 6.1 关键参数类别

- 输入与选择：`case-root / step3-root / case-id / max-cases`
- 执行控制：`workers / run-id / debug / debug-render`
- 输出控制：`out-root`

### 6.2 参数原则

- `Step4-7` 只暴露批处理所需的稳定参数
- 不暴露用于重写 Step3 规则的参数
- 不把 Step6 solver 常量、buffer 宽度、距离阈值写成长期业务契约

## 7. Acceptance

1. Anchor61 原始总量固定为 `61` 个 case，可批量运行
2. 默认正式全量验收集固定排除 `922217 / 54265667 / 502058682`，按剩余 `58` 个 case 统计；显式 `--case-id` 仍可单独复跑它们
3. `preflight.json / summary.json` 必须能直接表达：
   - `raw_case_count = 61`
   - `default_formal_case_count = 58`
   - `excluded_case_ids`
   - `effective_case_ids`
   - `missing_case_ids`
   - `failed_case_ids`
4. `failed_case_ids` 只记录运行期失败或未写出完整 case 输出的 case，不等价于 `step45_state = not_established` 或 `step7_state = rejected`
5. Step45 与 Step67 的平铺 PNG 数量都必须与该 run 的 `effective_case_ids` 一致
6. `Step7 accepted` 必须同时满足：
   - `Step1 must-cover`
   - `Step3 legal space`
   - 条件性 `Step4 local required RC must-cover`
   - `Step5 / Step6` hard foreign exclusion
   - `Step6 geometry established`
   - 若 `two_node_t_bridge_applied = true`，则 `Step67` 几何不得因横方向截断破坏 bridge 连通性
7. `Step7 rejected` 表示当前冻结约束下不成立；视觉审计类只用于人工复核分型
