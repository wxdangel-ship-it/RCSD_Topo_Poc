# T03 - INTERFACE_CONTRACT

## 定位

本文件是 `t03_virtual_junction_anchor` 的稳定接口契约速查，主要给实现、运行、联调和 Agent 维护使用。

业务需求优先看 `SPEC.md`；架构设计按 `architecture/01~06` 阅读；历史命名边界见 `architecture/03-solution-strategy.md`。本文件只保留输入、输出、状态、入口和最小审计字段，不展开业务策略。

## 1. 契约边界

- 模块 ID：`t03_virtual_junction_anchor`
- 当前正式模板：`center_junction`、`single_sided_t_mouth`
- 当前正式输入模式：Anchor61 `case-package`、internal full-input 共享图层局部查询
- 当前正式业务主链：`Step1~Step7`
- 当前不处理：`diverge / merge / continuous divmerge / complex 128`、环岛、概率化排序
- 当前不新增 repo 官方 Step7 / finalization CLI
- `Association` 只作为 `Step4 + Step5` 的历史实现 / 兼容命名
- `Finalization` 只作为 `Step6 + Step7` 的历史实现 / 兼容命名

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
- `step3_allowed_space.gpkg`
- `step3_status.json`
- `step3_audit.json`

`Step4~Step7` 必须消费冻结的 Step3 工件，不得回写 Step3，也不得在 Step3 关键前提缺失时静默 fallback。

### 2.2 internal full-input 输入

internal full-input 从共享图层中发现候选 case 并构建局部上下文。共享层至少包括：

- `nodes`
- `roads`
- `DriveZone`
- `RCSDRoad`
- `RCSDNode`

候选代表 node 只允许满足：

- `has_evd = yes`
- `is_anchor = no`
- `kind_2 in {4, 2048}`

`is_anchor in {yes, null, fail1, fail2, fail3, fail4, fail4_fallback}` 与 `kind_2 in {8, 16, 128}` 不进入 T03 full-input 候选。

### 2.3 字段与 CRS

- 空间处理 CRS：`EPSG:3857`
- `nodes` 至少需要：`id`、`mainnodeid`、`has_evd`、`is_anchor`、`kind_2`、`grade_2`
- `nodes.grade` 若存在则保留给 T05 `level`；缺失不阻塞 T03
- `nodes.closed_con` 若存在则保留给 T05 `is_highway`；缺失不阻塞 T03
- `roads / rcsdroad` 至少需要：`id`、`snodeid`、`enodeid`、`direction`
- `rcsdroad.formway` 是可选字段；若存在且可解析，Step4 调头口判定必须优先采用该字段
- `rcsdnode` 至少需要：`id`、`mainnodeid`

## 3. 状态和值域

### 3.1 模板

- `kind_2 = 4 -> center_junction`
- `kind_2 = 2048 -> single_sided_t_mouth`

### 3.2 Step3 prerequisite

- `step3_status.json` 必须提供 `step3_state`
- `step3_status.json` 必须直接提供非空 `selected_road_ids`
- `selected_road_ids` 缺失时不得回退到 Step1 target roads
- prerequisite 缺失时，case 必须显式记录 blocker 与 issue

### 3.3 Step4 association

`association_class` 只允许：

- `A`：主关联成立
- `B`：支持性关联成立，通常是 support-only
- `C`：关联不成立或不应消费

`association_state` 只允许：

- `established`
- `review`
- `not_established`

RCSD 语义分层固定为：

- `related`：当前 SWSD 路口在 RCSD 下的强语义关联证据层
- `local_required`：Step6 在 directional boundary 内实际消费的 must-cover 子集
- `foreign_mask`：Step5 进入 Step6 hard subtract 的 road-like 掩膜来源

`related` 不等于全长 must-cover，`foreign_mask` 不得包含已判定为 `related` 的 RCSDRoad。

### 3.4 Step6 geometry

Step6 必须在以下条件内生成候选几何：

- 不突破 Step3 legal space
- 不纳入 Step5 hard negative mask
- 满足 Step1 semantic junction must-cover
- 满足条件性 `local required RC must-cover`
- 先确定 directional boundary，再在边界内构面

Step6 不冻结 solver 常量、阈值、buffer 或具体构面参数。

### 3.5 Step7 formal status

`step7_state` 只允许：

- `accepted`
- `rejected`

批量运行另需区分：

- `runtime_failed`

`V1~V5` 只属于 review-only 层，不得反写为正式机器状态。

### 3.6 状态字段分工

T03 不允许把不同层级的状态字段混用：

| 字段 | 业务含义 | 禁止解释 |
|---|---|---|
| `association_class` | Step4 对 RCSD 证据角色的分类：主关联、支持性关联、无可消费关联 | 不得解释为视觉等级或 Step7 发布状态 |
| `association_state` | Step4 关联判断的执行状态：已稳定、需 review 或被前置条件阻断 | 不得解释为 SWSD-RCSD relation 成功 |
| `step7_state` | Step7 对虚拟面是否可 formal 发布的判断 | 不得解释为 RCSD relation 一定成功 |
| `relation_state / status_suggested` | T05 handoff 是否可消费为语义路口 relation 的建议 | 不得由 `V1~V5` 或 review PNG 反推 |

`association_class = C` 且 `association_state = established` 表示 Step4 已稳定判定“无可消费 RCSD relation”，不是 relation 成功。若该 case 的 Step7 surface 被 accepted，`t03_swsd_rcsd_relation_evidence.*` 仍必须表达 `no_related_rcsd / status_suggested = 1`。

`association_class = B` 的 support-only case 可以在 Step6/Step7 几何收敛后 accepted，但 relation evidence 仍必须表达 `rcsd_present_not_junction / status_suggested = 1`。

## 4. 输出契约

### 4.1 case 级 formal 输出

- Step3：`step3_allowed_space.gpkg`、`step3_status.json`、`step3_audit.json`
- Association 兼容输出：`association_required_*`、`association_support_*`、`association_excluded_*`、`association_required_hook_zone.gpkg`、`association_status.json`、`association_audit.json`
- Step6：`step6_polygon_seed.gpkg`、`step6_polygon_final.gpkg`、`step6_constraint_foreign_mask.gpkg`、`step6_status.json`、`step6_audit.json`
- Step7：`step7_final_polygon.gpkg`、`step7_status.json`、`step7_audit.json`

`association_*` 与 `step7_*` 是兼容输出文件名，不代表正式需求主结构继续使用 `Association / Finalization`。

### 4.2 case 级 review-only 输出

`association_review.png`、`step7_review.png`、`t03_review_*`、`visual_checks/` 只用于人工复核，不参与 formal status、summary 或 relation evidence 成功状态判定。

### 4.3 batch / full-input run root 输出

必须包含 `preflight.json`、`summary.json`、`cases/`、`virtual_intersection_polygons.gpkg`、`nodes.gpkg`、`nodes_anchor_update_audit.*`、`t03_swsd_rcsd_relation_evidence.*`、`intersection_match_t03.geojson`、`intersection_match_t03_summary.json`、`intersection_match_t03_cardinality_errors.csv/json`。

可包含 review-only 索引：`t03_review_index.csv`、`t03_review_summary.json`。

Release / `DEBUG_VISUAL != 1` 默认不生成最终审计图片；Debug / `DEBUG_VISUAL = 1` 可生成 review-only 图片。

### 4.4 internal 观测与恢复输出

`_internal/<RUN_ID>/` 至少包含 manifest、progress、performance、failure、`case_progress/*.json`、`terminal_case_records/<case_id>.json`、`t03_streamed_case_results.jsonl` 与 `t03_perf_audit_*`。其中 terminal record 是 authoritative terminal source，streamed JSONL 只是 append log。

## 5. 关键输出语义

### 5.1 `virtual_intersection_polygons.gpkg`

- 只聚合 `step7_state = accepted` 的 case final polygon
- 输出 CRS 固定为 `EPSG:3857`
- compatibility 字段不得反向决定 formal publishing eligibility

### 5.2 `nodes.gpkg`

基于 full-input 输入整层 `nodes.gpkg` copy-on-write 生成；不得重写 geometry、丢 CRS 或改变非目标字段。只允许更新当前批次 selected / effective case 的代表 node `is_anchor`：`accepted -> yes`，`rejected / runtime_failed / formal result missing -> fail3`。Relation 基数冲突、road-only 或 T05 前无法发布 1:1 relation 只影响 `intersection_match_t03` / relation evidence / T05 审计，不得把已 accepted 的代表 node 回退为 `no`。`fail3` 只属于 T03 downstream output 语义，不回写输入原始 nodes。

### 5.3 `nodes_anchor_update_audit.*`

每条审计记录至少包含：`case_id`、`representative_node_id`、`previous_is_anchor`、`new_is_anchor`、`step7_state`、`reason`。

### 5.4 `t03_swsd_rcsd_relation_evidence.*`

- 属于 T05 handoff 输入，不是最终 `intersection_match_all.geojson`
- 输出坐标 CRS 为 `EPSG:3857`
- JSON metadata 必须记录 `target_crs = EPSG:3857`
- `target_id` 优先取 SWSD `mainnodeid`，为空时取代表 node `id`
- `level` 来自代表 node `grade`；缺失填 `-1`，不得反推
- `is_highway` 来自代表 node `closed_con`；缺失填 `-1`，不得反推
- `status_suggested = 0` 只允许在 `association_class = A`、`step7_state = accepted` 且存在 `required_rcsdnode_ids` 时出现
- `association_class = B` 必须输出 `rcsd_present_not_junction / status_suggested = 1`
- `visual_review_class / V1~V5 / business_outcome_class` 不得决定 relation evidence 成功状态

`relation_state` 值域：`success_required_rcsd_junction`、`rcsd_present_not_junction`、`no_related_rcsd`、`geometry_not_accepted`、`ambiguous_review`。

### 5.5 `intersection_match_t03.geojson`

属于 T03 batch / full-input 的最终语义路口 relation 成果，输出 CRS 为 `CRS84`，只发布通过 1:1 校验的 SWSD-RCSD 语义路口关系。`target_id` 为 SWSD 语义路口 id，`base_id` 为 RCSD 语义路口 id，`status = 0` 表示成功 relation。校验结果写入 `intersection_match_t03_cardinality_errors.csv/json` 与 `intersection_match_t03_summary.json`。

可选外部校验输入为 `intersection_match_all_path` / `INTERSECTION_MATCH_ALL_PATH`；旧 `intersection_match_t07_path` / `INTERSECTION_MATCH_T07_PATH` 仅作为兼容别名保留，不得与不同文件的 `intersection_match_all_path` 同时提供。

## 6. 最小审计字段

`association_status.json` 至少覆盖 case/template、association result、Step3 prerequisite、RCSD evidence、u-turn audit、connector/group audit 六组信息，核心字段包括 `case_id`、`template_class`、`association_class`、`association_state`、`reason`、`step3_state`、`selected_road_ids`、`required_*`、`support_*`、`excluded_*`、`related_*`、`foreign_mask_source_rcsdroad_ids`、`u_turn_*`、`nonsemantic_connector_rcsdnode_ids`、`true_foreign_rcsdnode_ids`、`degree2_merged_rcsdroad_groups`。

`step6_status.json` 至少覆盖几何结果、must-cover、legal space、direction boundary、foreign exclusion、related/local-required/foreign-mask 和 Step3 bridge 继承信息，核心字段包括 `step6_state`、`geometry_established`、`reason`、`semantic_junction_cover_ok`、`required_rc_cover_ok`、`within_legal_space_ok`、`within_direction_boundary_ok`、`foreign_exclusion_ok`、`related_*`、`local_required_*`、`foreign_mask_source_rcsdroad_ids`、`step3_two_node_t_bridge_inherited`。

`step7_status.json` 至少覆盖 case/template、association、Step6、Step7、accepted、reason、root cause 和 note。不得包含 `visual_review_class`、`visual_audit_class`、`visual_audit_family`、`manual_review_recommended`。

`summary.json` 只统计 formal 口径，不得写入 `visual_v1_count / visual_v2_count / visual_v3_count / visual_v4_count / visual_v5_count`。

## 7. 入口契约

### 7.1 repo 官方 CLI

```bash
.venv/bin/python -m rcsd_topo_poc t03-rcsd-association --help
.venv/bin/python -m rcsd_topo_poc t03-step3-legal-space --help
```

两个 CLI 分别对应当前 `Step4 + Step5` RCSD 关联阶段入口与冻结 Step3 合法活动空间入口。

### 7.2 internal full-input 脚本

- `scripts/t03_run_internal_full_input_8workers.sh`
- `scripts/t03_watch_internal_full_input.sh`
- `scripts/t03_run_internal_full_input_innernet.sh`
- `scripts/t03_run_internal_full_input_innernet_flat_review.sh`

主脚本可选读取 `INTERSECTION_MATCH_ALL_PATH`，用于校验并生成 `intersection_match_t03.geojson`。缺省时仍输出 T03 自身 relation 成果。

历史 finalization wrapper 已退役；当前不登记兼容 wrapper，不新增 repo 官方 Step7 / finalization CLI。

## 8. 验收口径

- Anchor61 原始总量固定为 `61` 个 case。
- 默认正式全量验收集固定排除 `922217 / 54265667 / 502058682`，按剩余 `58` 个 case 统计。
- 显式 `--case-id` 仍可单独复跑被默认排除的 case。
- `failed_case_ids` 只记录运行期失败或未写出完整 case 输出的 case，不等价于 `association_state = not_established` 或 `step7_state = rejected`。

`Step7 accepted` 必须同时满足：

- Step1 must-cover
- Step3 legal space
- 条件性 Step4 local required RC must-cover
- Step5 / Step6 hard foreign exclusion
- Step6 geometry established
- 若 `two_node_t_bridge_applied = true`，几何不得因横方向截断破坏 bridge 连通性

`Step7 rejected` 表示当前冻结约束下不成立；视觉审计类只用于人工复核分型。
