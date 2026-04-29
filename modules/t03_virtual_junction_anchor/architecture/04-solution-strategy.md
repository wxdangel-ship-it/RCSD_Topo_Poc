# 04 Solution Strategy

## 1. 策略总览

T03 当前处理策略按正式业务主链 `Step1~Step7` 组织：

1. 建立当前 case 的代表节点、局部道路、DriveZone、RCSDRoad、RCSDNode 与冻结前置上下文。
2. 将 case 限定到当前正式支持模板：`center_junction` 或 `single_sided_t_mouth`。
3. 使用冻结合法空间作为不可反向篡改的前置约束。
4. 识别当前语义路口与 RCSD 的 `A / B / C` 关联关系，并形成 `related` 证据层。
5. 将不应进入当前路口面的 RCSD 对象分为 `foreign_mask` hard negative 或 audit-only foreign。
6. 在合法空间、方向边界、local required RC 与 hard negative mask 约束下生成最终候选几何。
7. 将结果发布为 `accepted / rejected`，并生成 formal、review-only 与 internal full-input 成果。

历史 `Association` 与 `Finalization` 不再作为方案主结构；它们的当前含义见 `10-business-steps-vs-implementation-stages.md`。

## 2. 实现分层

- `association_loader.py` 与 full-input shared query 层负责 `Step1 / Step2` 的输入受理、局部上下文与模板归类。
- `step3_engine.py` 与 `legal_space_*` 文件负责 `Step3` 合法空间冻结。
- `step4_association.py` 负责 `Step4` RCSD 关联语义识别。
- `step5_foreign_filter.py` 负责 `Step5` foreign / excluded 分组与审计。
- `step6_geometry.py` 负责 `Step6` 受约束几何生成。
- `step7_acceptance.py`、`finalization_outputs.py` 与 `t03_batch_closeout.py` 负责 `Step7` 发布、写盘与批量 closeout。

## 3. internal full-input 主链

internal full-input 不再把“先切最小 case-package 再 batch”视为默认主形态。当前主链为：

1. `candidate discovery`
2. `shared handle preload`
3. `per-case local context query`
4. direct `Step1~Step7` case execution
5. streamed / terminal state 写出
6. batch closeout

主运行脚本与监控脚本：

- `scripts/t03_run_internal_full_input_8workers.sh`
- `scripts/t03_watch_internal_full_input.sh`

历史 finalization shell wrapper 已退役，不承担模块级主命名。

## 4. 输出策略

- case 级 formal 输出保留现有文件名，包括 `association_*`、`step6_*`、`step7_final_polygon.gpkg`、`step7_*`。
- review-only 输出保留 `association_review.png`、`step7_review.png` 与 `t03_review_*` 目录。
- batch / full-input formal 输出固定包括：
  - `virtual_intersection_polygons.gpkg`
  - `nodes.gpkg`
  - `nodes_anchor_update_audit.csv`
  - `nodes_anchor_update_audit.json`
- `_internal/<RUN_ID>/terminal_case_records/<case_id>.json` 是 authoritative terminal state。
- `t03_streamed_case_results.jsonl` 是 compact append log，不作为唯一准真值。

## 5. 关键业务策略

- `Step3` 的合法空间、负向掩膜、must-cover 与 no-silent-fallback 语义必须保持冻结，不由后续步骤回写。
- `Step4` 的 `A / B / C` 是业务关联解释，不是视觉结果等级。
- `Step4` 的调头口判定优先采用 `RCSDRoad.formway`：当当前活动 RCSDRoad 集存在可解析 `formway` 字段时，`(formway & 1024) != 0` 是唯一调头口条件，字段名大小写不敏感；只有没有可解析 `formway` 时才回退到 strict 几何判定。
- 无 `formway` 的 strict 几何 fallback 必须基于“两个不同 RCSD 语义路口、两端语义折叠后均为 effective degree=3、两端主干 pair 共线、两端主干轴近似平行、可信方向证明两条主干方向相反”。方向不可用或不可信时只能进入 suspect 审计，不直接过滤。
- `Step4` 必须先保护路口间由 `degree = 2` connector 串接的同路径 `RCSDRoad` chain，再执行最终调头口过滤；旧几何 fallback 不得仅凭长度 / 对向近似误判同路径短分段。若 road 已满足 strict 几何 fallback，则可覆盖同路径保护进入最终调头口集合；若 tentative 调头过滤后才形成 degree-2 同路径证据，最终过滤前必须回补复核。
- `Step4 / Step5 / Step6` 的 RCSD 口径分为三层：`related` 表示完整关联证据，`local_required` 表示 directional boundary 内 must-cover 子集，`foreign_mask` 表示 Step6 hard subtract 来源。
- `related_outside_scope_rcsdroad_ids` 只能从 `required_rcsdroad_ids` 经 allowed/candidate 范围内的非语义 connector 做一跳延伸；不得从 support/group related road 外扩，不得递归多跳吞入远端 road。遇到有效 RCSD 语义路口边界、远端节点未打包 / 非 active，或 connector 不在当前 allowed/candidate 口径内时必须停止，不能把跨路口 RCSDRoad 拉入当前 related。非空且非 `0` 的 `mainnodeid` 只是候选 / grouping 信号，不单独构成停止条件。
- 对共享同一非空 `mainnodeid` 且空间紧凑的多点 RCSD 候选组，Step4 必须按 group 计算 connector degree；若 group effective degree = `2`，仍按非语义 connector 处理。当该 group 非 degree-2 且至少两个 incident road 已进入 related 时，同组 active node 进入 related。其他同组 incident road 不能仅因 group 成立自动进入 related，仍需按当前 case 路径、scope 与 foreign mask 规则独立判定。
- Step4 的 required core 需要额外通过模板相关 gate：`center_junction` 必须有代表点附近的 anchor-local 语义组、近邻成对语义组，或与当前 SWSD 路口结构一致且偏移受限的紧凑高阶 RCSD 复合语义组；`single_sided_t_mouth` 必须有 anchor-local 语义组、横向成对语义组、代表点近处的紧凑复合语义组，或 allowed-only 的紧凑复合语义组。已落在当前 SWSD surface 内但不满足 anchor-local / 成对条件的 single-sided compact group，不得仅凭 compact 身份升格为 A 类。
- Step4 对 `RCSDNode` 候选升格 / 降级必须写入 `required_rcsdnode_gate_audit` 与 `required_rcsdnode_gate_dropped_ids`，确保 A/B 边界可追溯。
- `Step5` 的 hard negative mask 当前仅由 `foreign_mask_source_rcsdroad_ids / excluded_rcsdroad -> road-like 1m mask` 进入 `Step6`；已判定为 `related` 的 RCSDRoad 不进入 hard mask。
- `Step6` 必须在 directional boundary 内构面，不允许为满足 required RC 而突破边界。
- `Step6` 对 B 类 support-only case 可以加入目标节点附近 seam bridge 修补中心缝隙，但该 bridge 仍受 legal space、directional boundary 与 hard negative mask 约束。
- `Step7` 只发布 `accepted / rejected`；`V1~V5` 只属于 review-only 层。
- review PNG 深红 RCSDRoad 表达强语义 `related_rcsdroad_ids` / `required_rcsdroad_ids`；`support_rcsdroad_ids` 保持 amber 辅助证据表达，不参与 required 延伸口径。
- 对 `single_sided_t_mouth + association_class=A`，横方向口门按“竖向 RCSDRoad seed -> 横向 tracing -> terminal RCSDNode -> +5m -> stop at next directly-associated semantic junction”求解；Step4 强相关 RCSD 语义路口最多两个。若远端下一语义路口只承担道路延伸终点角色，不进入当前 required core，也不得把该远端之后的 incident road 纳入当前 related；强相关集合能覆盖横向两侧且不缩短已确认 terminal extent 时用于收敛 tracing，否则保留既有可达 endpoint tracing。Step4 已标记的 overflow / remote terminal node 不得被 fallback tracing 再次提升为 terminal。
- 对冻结 `Step3` 已应用 `two_node_t_bridge` 的 case，后续几何必须继承该中心桥接支撑，不能由横向裁剪引入中心断开或桥位空洞。

## 6. 性能与观测策略

- shared-layer 查询使用空间索引与缓存，不回退到全层线性扫描。
- root progress / performance 文件受 flush gate 控制，避免每 case 高频重写。
- case-level terminal record 使用 atomic write。
- perf audit 继续记录 `candidate_discovery / shared_preload / local_feature_selection / step3 / step4 / step5 / step6 / step7 / output_write / observability_write` 等阶段耗时。
- review PNG 在 production no-debug 路径默认关闭；开启 review 时仍保持现有平铺输出契约。
