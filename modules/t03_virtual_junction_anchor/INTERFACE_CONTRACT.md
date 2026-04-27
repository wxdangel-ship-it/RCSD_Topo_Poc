# T03 - INTERFACE_CONTRACT

## 定位

本文件是 `t03_virtual_junction_anchor` 的稳定契约面。

T03 的正式业务目标是：面向当前语义路口，在冻结的合法活动空间内识别与 RCSD 的有效关联关系，构造受约束的最终路口面，并输出正式结果、复核结果与批量执行成果。

正式业务主链按 `Step1~Step7` 表达：

1. `Step1`：当前 case 受理与局部上下文建立
2. `Step2`：模板归类
3. `Step3`：合法活动空间冻结
4. `Step4`：RCSD 关联语义识别
5. `Step5`：foreign / excluded 负向约束
6. `Step6`：受约束几何生成
7. `Step7`：最终验收与发布

`Association` 与 `Finalization` 是历史实现阶段、现有文件名前缀、代码符号和兼容说明，不再作为正式需求主结构。映射关系见 `architecture/11-business-steps-vs-implementation-stages.md`。

## 1. 模块范围

### 1.1 当前正式支持

- 模块 ID：`t03_virtual_junction_anchor`
- 当前正式模板：
  - `center_junction`
  - `single_sided_t_mouth`
- 当前正式输入模式：
  - Anchor61 `case-package`
  - internal full-input 共享图层局部查询
- 当前正式成果：
  - case 级状态、审计、最终路口面与 review 产物
  - batch / full-input 聚合路口面
  - full-input 下游 `nodes.gpkg`
  - `nodes_anchor_update_audit.csv / nodes_anchor_update_audit.json`
  - authoritative terminal case records

### 1.2 当前非目标

- 不处理 `diverge / merge / continuous divmerge / complex 128`
- 不处理环岛或概率化排序
- 不在 T03 后续步骤中重新定义 Step3 的合法空间规则
- 不新增、删除或重命名 repo 官方 CLI
- 不把 solver 常量、buffer 宽度、cover ratio 或单轮调参结果冻结为长期业务契约
- 不再保留历史阶段输出命名

## 2. 输入契约

### 2.1 case-package 输入

每个 case 至少包含：

- `manifest.json`
- `size_report.json`
- `drivezone.gpkg`
- `nodes.gpkg`
- `roads.gpkg`
- `rcsdroad.gpkg`
- `rcsdnode.gpkg`

冻结前置结果至少包含：

- `step3_allowed_space.gpkg`
- `step3_status.json`
- `step3_audit.json`

### 2.2 internal full-input 输入

internal full-input 从全量共享图层出发自动发现候选 case，并构建局部上下文。共享层至少包括：

- `nodes`
- `roads`
- `DriveZone`
- `RCSDRoad`
- `RCSDNode`

internal full-input 当前主链是：

1. `candidate discovery`
2. `shared handle preload`
3. `per-case local context query`
4. direct `Step1~Step7` case execution
5. terminal record / streamed append log 写出
6. batch closeout

### 2.3 字段与 CRS 前提

- 所有空间处理统一使用 `EPSG:3857`。
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
- `kind_2` 当前只支持：
  - `4 -> center_junction`
  - `2048 -> single_sided_t_mouth`

## 3. Step1~Step7 正式业务契约

### 3.1 Step1：当前 case 受理与局部上下文建立

业务目标：

- 受理当前 case
- 确定代表节点、语义路口集合和局部处理上下文
- 形成后续步骤可消费的最小上下文对象

主要输出：

- `representative_node_id`
- `semantic_junction_set`
- 当前 case 局部 roads / DriveZone / RCSDRoad / RCSDNode
- 当前 case 与 full-input run 的审计定位信息

Step1 不负责最终正确性判断，也不负责几何生成。

### 3.2 Step2：模板归类

业务目标：

- 将当前 case 归入正式支持模板
- 明确后续模板特定路径

正式模板只允许：

- `center_junction`
- `single_sided_t_mouth`

不属于上述模板的 case 不进入当前正式处理范围。

### 3.3 Step3：合法活动空间冻结

业务目标：

- 冻结当前 case 的合法活动空间
- 明确哪些空间允许进入最终结果
- 明确哪些空间必须被屏蔽
- 为后续步骤提供不可反向篡改的前置约束层

当前 Step3 冻结规则按中文业务语义表达为：

1. 道路归属规则：只允许当前 case 明确选中的道路集合进入合法活动空间。
2. DriveZone 约束规则：最终合法空间必须落在当前 case 对应的有效 DriveZone 范围内。
3. 邻近语义路口切断规则：当前 case 不能跨越相邻语义路口去扩张合法空间。
4. foreign 对象屏蔽规则：当前 case 的合法空间不能吞入已识别为 foreign 的对象。
5. foreign MST 补充切断规则：对存在拓扑干扰但不直接落在当前 local patch 的对象，用 MST 方式补充约束。
6. must-cover 规则：当前 case 的核心语义对象必须被合法空间覆盖，否则直接暴露为异常。
7. single-sided opposite-side guard 规则：单侧 T 型场景下要抑制对向误扩张。
8. no-silent-fallback 规则：关键道路集缺失时必须显式失败，不能隐式放宽。

冻结前置校验：

- `step3_status.json` 必须提供 `step3_state`
- `step3_status.json` 必须直接提供非空 `selected_road_ids`
- 不允许在 `selected_road_ids` 缺失时静默回退到 Step1 target roads
- prerequisite 缺失时，case 必须显式记录 blocker 与 issue

### 3.4 Step4：RCSD 关联语义识别

业务目标：

- 在 Step3 冻结前提下解释当前语义路口与 RCSD 的关系
- 识别哪些 RCSD 对象对当前结果是必须的、可支持的、需排除的
- 形成后续 Step5 / Step6 可消费的 RCSD 语义事实

`association_class` 只允许：

- `A`
- `B`
- `C`

业务含义：

- `A`：主关联成立。当前 case 与 RCSD 的对应关系清晰，核心 RCSD 对象已经稳定识别，可作为后续几何生成的主事实基础。
- `B`：支持性关联成立。当前 case 与 RCSD 的关系有一定证据，但不足以形成完整主关联；可继续进入后续步骤，但应保留 review 风险。
- `C`：关联不成立或不应消费。当前 RCSD 对象不应被当前 case 使用，不应进入最终几何生成。

兼容状态字段：

- `association_state = established`
- `association_state = review`
- `association_state = not_established`

`association_state` 是现有输出兼容字段名，其业务归属为 `Step4 / Step5` 的中间状态，不等价于 `Step7` 最终发布状态。

### 3.5 Step5：foreign / excluded 负向约束

业务目标：

- 从 Step4 结果中找出不应进入最终路口面的 RCSD 对象
- 区分正式 hard negative 对象与 audit-only foreign 对象
- 形成 Step6 可消费的 hard negative mask

当前 Step5 应排除的对象主要包括：

1. 不属于当前 case 的 RCSDRoad。
2. 方向上不应被当前 case 消费的对象。
3. 会导致结果吞入相邻路口或相邻支路的对象。
4. 经 Step4 判定为 `C` 类关联的对象。

当前正式 hard negative 来源：

- `excluded_rcsdroad -> road-like 1m mask`

node 类 `excluded / foreign` 当前保留在审计层，不进入本轮 hard subtract。`association_foreign_swsd_context.gpkg / association_foreign_rcsd_context.gpkg` 为兼容性审计产物，可以为空，不应再被解释为 hard negative polygon context。

### 3.6 Step6：受约束几何生成

业务目标：

- 在 Step3 合法空间、Step4 主关联、Step5 hard negative 约束共同作用下，构造最终路口面几何
- 形成满足模板要求、事实约束和几何约束的候选最终面

硬优先级固定为：

1. 不得突破 Step3 legal space
2. 不得纳入 Step5 excluded / hard negative mask
3. 必须满足 Step1 semantic junction must-cover
4. 必须满足条件性 `local required RC must-cover`
5. 上述成立后才允许做几何优化

关键规则：

- 必须先确定 directional boundary，再在该边界内构面。
- 不允许先裁剪再把 required RC 整体补回边界外。
- final geometry 不得突破 directional boundary。
- `required RC must-cover` 当前只对 directional boundary 内的 local required RC 成立。
- directional boundary 外的 required RCSDRoad / RCSDNode 不得作为 accepted 的硬失败条件。
- 当前正式契约不冻结 Step6 solver 常量、阈值与具体构面参数。

### 3.7 Step7：最终验收与发布

业务目标：

- 对 Step6 结果做最终正式判定
- 生成正式发布结果、review 结果和 batch 聚合成果
- 支撑 internal full-input 的批量运行与最终发布

正式机器状态只允许：

- `accepted`
- `rejected`

批量运行还必须显式区分：

- `runtime_failed`

规则：

- `Step7` 只基于冻结的 `Step1~Step6` 结果发布，不重新定义业务事实。
- `V1~V5` 只属于视觉审计层，不等价于机器主状态。
- `terminal_case_records/<case_id>.json` 是 internal full-input authoritative terminal state。
- `t03_streamed_case_results.jsonl` 是 compact append log，不作为唯一准真值。

## 4. 稳定业务语义

### 4.1 当前 SWSD surface 过滤

- 每个 case 只处理“当前 SWSD 路口所在道路面”的 SWSD / RCSD 对象。
- 道路面外对象不进入当前 case 主结果集合。
- 审计中必须区分：
  - `active_rcsdnode_ids / active_rcsdroad_ids`
  - `ignored_outside_current_swsd_surface_rcsdnode_ids / ignored_outside_current_swsd_surface_rcsdroad_ids`

### 4.2 RCSD 调头口过滤

- 若某条 `RCSDRoad` 的两端分别关联到方向相反的 `RCSDRoad`，则该 `RCSDRoad` 视为 `调头口 RCSDRoad`。
- `调头口 RCSDRoad` 在当前 case 的 RCSD 语义处理中视为不存在：
  - 不进入后续 `candidate / required / support / excluded` 分类。
  - 不得在 Step6 被重新解释为 local required RC。
- 去除 `调头口 RCSDRoad` 后，后续 `degree = 2 connector` 识别与 `RCSDRoad chain merge` 必须基于过滤后的活动集重新计算。
- 审计至少要稳定表达：
  - `active_rcsdroad_ids_before_u_turn_filter`
  - `u_turn_rcsdroad_ids`
  - `u_turn_rcsdroad_audit`

### 4.3 degree-2 connector 语义

- `degree = 2` 的 `RCSDNode` 只视为 connector，不进入 required semantic core。
- connector node 与真正 foreign node 必须在审计上分开记录：
  - `nonsemantic_connector_rcsdnode_ids`
  - `true_foreign_rcsdnode_ids`
- 经 `degree = 2` connector 串接的 candidate `RCSDRoad`，必须先按同一 `RCSDRoad chain` 合并，再参与 `required / support / excluded` 分类。
- 该 chain merge 当前不考虑角度门禁。
- 审计至少要稳定表达：
  - `degree2_merged_rcsdroad_groups`

### 4.4 single_sided_t_mouth 规则

- 对 `single_sided_t_mouth`，若 support RCSDRoad 在当前竖向退出链附近出现平行重复，按“更贴近竖方向退出当前面一侧”保留。
- 对 `single_sided_t_mouth + association_class=A`，横方向口门按“竖向 RCSDRoad seed -> 横向 tracing -> terminal RCSDNode -> +5m -> stop at next directly-associated semantic junction”求解。
- tracing 过程中的 `RCSDRoad` 不要求整体完全落在当前候选空间内；只要最终确认的 `RCSDNode` 落在横方向候选空间内，即可视为当前 tracing 有效。
- 若 tracing 无法在横方向两侧都确认 terminal `RCSDNode`，则当前 A 类横向口门特化规则不成立，横方向回到 generic directional boundary。
- 若冻结 Step3 已对当前 case 标记 `two_node_t_bridge_applied = true`，则后续 directional boundary / polygon seed 必须继承该 bridge corridor。

## 5. 输出契约

### 5.1 case 级 formal 输出

- `step3_allowed_space.gpkg`
- `step3_status.json`
- `step3_audit.json`
- `association_required_rcsdnode.gpkg`
- `association_required_rcsdroad.gpkg`
- `association_support_rcsdnode.gpkg`
- `association_support_rcsdroad.gpkg`
- `association_excluded_rcsdnode.gpkg`
- `association_excluded_rcsdroad.gpkg`
- `association_required_hook_zone.gpkg`
- `association_status.json`
- `association_audit.json`
- `step6_polygon_seed.gpkg`
- `step6_polygon_final.gpkg`
- `step6_constraint_foreign_mask.gpkg`
- `step6_status.json`
- `step6_audit.json`
- `step7_final_polygon.gpkg`
- `step7_status.json`
- `step7_audit.json`

`association_*` 与 `step7_*` 是当前正式输出命名。

### 5.2 case 级 review-only 输出

- `association_review.png`
- `step7_review.png`

### 5.3 batch / full-input run root 输出

- `preflight.json`
- `summary.json`
- `cases/`
- `t03_review_index.csv`
- `t03_review_summary.json`
- `t03_review_accepted/`
- `t03_review_rejected/`
- `t03_review_v2_risk/`
- `t03_review_flat/`
- `visual_checks/`
- `virtual_intersection_polygons.gpkg`
- `nodes.gpkg`
- `nodes_anchor_update_audit.csv`
- `nodes_anchor_update_audit.json`

### 5.4 status / audit 字段

`association_status.json` 至少包含：

- `case_id`
- `template_class`
- `association_class`
- `association_state`
- `association_established`
- `reason`
- `key_metrics`
- `step3_state`
- `selected_road_ids`
- `association_executed / association_reason / association_blocker`
- `association_prerequisite_issues`
- `active_rcsdroad_ids_before_u_turn_filter`
- `u_turn_rcsdroad_ids`
- `required_rcsdnode_ids / required_rcsdroad_ids`
- `support_rcsdnode_ids / support_rcsdroad_ids`
- `excluded_rcsdnode_ids / excluded_rcsdroad_ids`
- `rcsd_semantic_core_missing`
- `nonsemantic_connector_rcsdnode_ids / true_foreign_rcsdnode_ids`
- `degree2_merged_rcsdroad_groups`

`step6_status.json` 至少包含：

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

`step7_status.json` 至少包含：

- `case_id`
- `template_class`
- `association_class`
- `association_state`
- `step6_state`
- `step7_state`
- `accepted`
- `reason`
- `root_cause_layer / root_cause_type`
- `note`

`step7_status.json` 不得包含：

- `visual_review_class`
- `visual_audit_class`
- `visual_audit_family`
- `manual_review_recommended`

正式 `summary.json` 只统计 formal 口径，不得写入 `visual_v1_count / visual_v2_count / visual_v3_count / visual_v4_count / visual_v5_count`。

### 5.5 batch aggregate 输出

`virtual_intersection_polygons.gpkg`：

- 属于当前 batch / full-input 的正式聚合成果图层。
- 聚合来源是各 case 最终 formal polygon；当前实现只纳入最终业务结果为非 failure 的 case。
- 输出 CRS 固定为 `EPSG:3857`。
- 当前字段集合与 T02 Stage3 official full-input 聚合成果层的实际代码实现对齐。
- `visual_review_class / official_review_eligible / failure_bucket` 属于 batch aggregate compatibility 字段，只允许停留在该聚合图层。

`nodes.gpkg`：

- 属于当前 batch / full-input 的正式成果图层。
- 基于 full-input 输入整层 `nodes.gpkg` copy-on-write 生成。
- 只允许更新当前批次 selected / effective case 对应代表 node 的 `is_anchor`：
  - `step7_state = accepted -> yes`
  - `step7_state = rejected -> fail3`
  - `runtime_failed / formal result missing -> fail3`
- 非代表 node 与未选中 node 保持输入值不变。
- `is_anchor = fail3` 只属于 T03 internal full-input 下游输出语义，不回写输入原始 nodes，也不修改 T02 / Step3 上游字段契约。

`nodes_anchor_update_audit.csv / nodes_anchor_update_audit.json`：

- 属于当前 batch / full-input 的正式审计工件。
- 每条审计记录至少包含：
  - `case_id`
  - `representative_node_id`
  - `previous_is_anchor`
  - `new_is_anchor`
  - `step7_state`
  - `reason`

## 6. internal 观测与恢复

`_internal/<RUN_ID>/` 至少包含：

- `t03_internal_full_input_manifest.json`
- `t03_internal_full_input_progress.json`
- `t03_internal_full_input_performance.json`
- `t03_internal_full_input_failure.json`
- `case_progress/*.json`
- `terminal_case_records/<case_id>.json`
- `t03_streamed_case_results.jsonl`
- `t03_perf_audit_*`

语义：

- `manifest` 承载 selected/discovered/excluded case 列表、输入路径、输出路径、shared-memory 摘要与 run 级静态语义。
- `progress` 承载 lightweight runtime counters：`phase / status / message / total / completed / running / pending / success / failed / last_completed / entered_case_execution`。
- `performance` 承载累计耗时、阶段耗时、stage timer、完成速率等性能统计。
- `terminal_case_records/<case_id>.json` 是 authoritative terminal source，优先用于 closeout、resume 与 retry-failed。
- `t03_streamed_case_results.jsonl` 是 compact append log，服务分析与快速扫描，不作为唯一准真值。
- 高频 JSON 写盘必须采用 temp file + atomic rename。

watch 默认 formal-first 口径：

- `total`
- `completed`
- `running`
- `pending`
- `success = accepted`
- `failed = rejected + runtime_failed`

默认不显示 `V1~V5`；仅当 `DEBUG_VISUAL=1` 时，允许从 review-only 工件读取视觉统计。

## 7. 入口契约

### 7.1 repo 官方入口

```bash
.venv/bin/python -m rcsd_topo_poc t03-rcsd-association --help
```

该 CLI 是当前 `Step4 + Step5` RCSD 关联阶段入口。

### 7.2 冻结前置入口

```bash
.venv/bin/python -m rcsd_topo_poc t03-step3-legal-space --help
```

### 7.3 internal full-input 脚本入口

- 主脚本：`scripts/t03_run_internal_full_input_8workers.sh`
- 主 watch：`scripts/t03_watch_internal_full_input.sh`
- 内网包装：`scripts/t03_run_internal_full_input_innernet.sh`
- 内网平铺目视包装：`scripts/t03_run_internal_full_input_innernet_flat_review.sh`
- 历史 finalization wrapper 已退役；当前不再登记兼容 wrapper。

当前不新增 repo 官方 Step7 / finalization CLI。

## 8. 验收口径

1. Anchor61 原始总量固定为 `61` 个 case，可批量运行。
2. 默认正式全量验收集固定排除 `922217 / 54265667 / 502058682`，按剩余 `58` 个 case 统计；显式 `--case-id` 仍可单独复跑它们。
3. `preflight.json / summary.json` 必须直接表达：
   - `raw_case_count = 61`
   - `default_formal_case_count = 58`
   - `excluded_case_ids`
   - `effective_case_ids`
   - `missing_case_ids`
   - `failed_case_ids`
4. `failed_case_ids` 只记录运行期失败或未写出完整 case 输出的 case，不等价于 `association_state = not_established` 或 `step7_state = rejected`。
5. `Step7 accepted` 必须同时满足：
   - Step1 must-cover
   - Step3 legal space
   - 条件性 Step4 local required RC must-cover
   - Step5 / Step6 hard foreign exclusion
   - Step6 geometry established
   - 若 `two_node_t_bridge_applied = true`，则几何不得因横方向截断破坏 bridge 连通性。
6. `Step7 rejected` 表示当前冻结约束下不成立；视觉审计类只用于人工复核分型。

## 9. 历史命名使用边界

- `Association` 只能作为 `Step4 + Step5` 的历史实现阶段、现有 CLI / 代码 / 输出兼容名出现。
- `Finalization` 只能作为 `Step6 + Step7` 的历史 finalization / delivery 阶段、现有代码 / 输出 / wrapper 兼容名出现。
- 主需求章节、业务目标和质量口径必须优先使用 `Step1~Step7`。
- 历史 closeout 文档保留追溯价值，但不替代本契约。
