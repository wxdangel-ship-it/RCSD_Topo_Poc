# 09 Quality Requirements

## 1. 业务正确性

- `Step1` 必须可追溯当前 case 的代表节点、语义路口集合、道路集合、DriveZone、RCSDRoad 与 RCSDNode。
- `Step2` 只允许当前正式模板：`center_junction / single_sided_t_mouth`。
- `Step3` 必须保持冻结前置语义：道路归属、DriveZone 约束、邻近路口切断、foreign 屏蔽、foreign MST 补充切断、must-cover、single-sided opposite-side guard、no-silent-fallback。
- `Step4` 必须稳定解释 `A / B / C` 三类 RCSD 关联结果，并可审计区分同路径 `RCSDRoad` chain、最终调头口、suspect 调头口、被同路径保护拒绝的调头候选；当 `RCSDRoad.formway` 存在时，`(formway & 1024) != 0` 是唯一调头口判定条件，未提供该字段时只允许 strict 几何 fallback，且方向不可用 / 不可信的几何候选只能审计不得过滤；同路径保护可被 strict 调头连接覆盖，短分段不再作为覆盖失败的独立条件；tentative 调头过滤后新增的同路径证据也必须在最终调头过滤前复核。
- `Step4 / Step5 / Step6` 必须可审计区分 `related / local_required / foreign_mask` 三层 RCSD 语义；`related` 不得被误作为全长 must-cover，`foreign_mask` 不得包含 related road。
- `related_outside_scope_rcsdroad_ids` 不得跨越有效 RCSD 语义路口边界；只能从 required core 经 allowed/candidate 范围内的非语义 connector 做一跳延伸，不得从 support/group related road 或远端 / 未打包节点继续外扩。非空且非 `0` 的 `mainnodeid` 只是候选 / grouping 信号，不单独构成停止条件。
- 共享同一非空 `mainnodeid` 且空间紧凑的多点 RCSD 候选组必须按 group 计算 effective degree；若 effective degree = `2`，仍按非语义 connector 处理。同组 road 必须只有在自身命中 local / outside-scope related 规则时才进入 `related_rcsdroad_ids`。
- required core 必须通过模板相关 gate：中心路口不能由远端单个 RCSD 语义组独立升格，但允许当前 SWSD 路口结构一致且偏移受限的紧凑高阶 RCSD 复合语义组升格；单侧 T 口不能由孤立远端单点独立升格，也不能由已落在当前 SWSD surface 内但非 anchor-local / 非成对的 compact group 独立升格。所有降级必须在 `required_rcsdnode_gate_audit` / `required_rcsdnode_gate_dropped_ids` 中可追溯。
- `RCSDNode` 的 required/support 关联必须有 incident `RCSDRoad` 证据，避免无拓扑连接的邻近点误升格为 related。
- `single_sided_t_mouth` 的强相关 RCSD 语义路口最多两个；远端下一语义路口只能作为道路延伸终点，不得把远端之后的 incident road 纳入当前 related；Step6 必须优先使用可完成两侧确认的 Step4 强相关集合，强相关集合不足以确认两侧时保留既有 endpoint tracing。
- `Step5` 必须区分正式 hard negative 对象与 audit-only foreign 对象。
- `Step6` 不得突破合法空间、directional boundary 或 excluded hard mask；B 类 support-only 的中心 seam bridge 只能在上述约束内修补目标节点附近缝隙，不得成为跨路口扩张。
- `Step7` 机器状态只允许 `accepted / rejected`；批量运行另需显式区分 `runtime_failed`。

## 2. 输出与契约稳定性

- 可批量：Anchor61 必须按 `61 raw / 58 default formal` 稳定落盘。
- 可发布：`virtual_intersection_polygons.gpkg` 是 batch / full-input 正式聚合成果层。
- 可发布：`nodes.gpkg` 只能更新当前批次 selected / effective case 的代表 node `is_anchor`；`accepted => yes`、`rejected / runtime_failed => fail3`，非代表 node 与未选中 node 必须保持输入值不变。
- 可一致：`nodes_anchor_update_audit.csv / nodes_anchor_update_audit.json` 的行集、计数与 `nodes.gpkg` 实际写值必须一致。
- 可兼容：现有 `association_*` 与 `step7_*` 输出文件名继续作为当前兼容契约保留，不因文档主结构切换而重命名。

## 3. Review 与 formal 分层

- `V1~V5` 只属于视觉审计层，不等价于正式机器状态。
- review PNG 中深红 RCSDRoad 只表达强语义 `related_rcsdroad_ids` / `required_rcsdroad_ids`；`support_rcsdroad_ids` 必须保持 amber 辅助证据表达；`foreign_mask` 只能以 mask 口径表达，不得伪装成 related 线条。
- `step7_status.json`、`step7_final_polygon.gpkg` 与正式 `summary.json` 不得写入 `visual_review_class / visual_audit_class / manual_review_recommended`。
- `t03_review_*`、`visual_checks/` 与 review PNG 是 review-only 产物。
- batch aggregate polygon 上的 review compatibility 字段不得反向渗透回 formal status / summary 面。

## 4. 观测、恢复与性能

- internal watch 默认只展示 formal-first 口径：`total / completed / running / pending / success / failed`；`success = accepted`，`failed = rejected + runtime_failed`。
- `DEBUG_VISUAL=1` 之外不得把 `V1~V5` 统计重新混入默认 formal monitor。
- `t03_internal_full_input_manifest.json` 与 `t03_internal_full_input_progress.json / t03_internal_full_input_performance.json` 必须保持 static-vs-runtime 分层。
- 高频 runtime 文件不得重写 selected/discovered 全量 case id 列表。
- 高频 observability JSON 写盘必须使用 atomic rename；early failure 时至少能读到 progress/failure 工件。
- `terminal_case_records/<case_id>.json` 必须作为 authoritative terminal state 支撑 closeout、resume 与 retry-failed。
- 可量化：阶段耗时必须覆盖 shared query、`Step3~Step7`、output write、observability write 与关键子 timer，用于后续性能审计。

## 5. 治理要求

- 模块文档面、项目级盘点、官方入口事实与当前实现保持一致。
- 正式主文档不再用 `Association / Finalization` 组织业务结构；历史阶段名只允许在实现映射、兼容说明、历史 closeout、现有输出/入口名解释中出现。
- 不把 solver 常量、启发式参数或单轮 closeout 结果误写成长期业务契约。
- 不新增、不删除、不重命名 repo 官方 CLI 或 shell wrapper，除非后续单独获得入口治理任务授权。
