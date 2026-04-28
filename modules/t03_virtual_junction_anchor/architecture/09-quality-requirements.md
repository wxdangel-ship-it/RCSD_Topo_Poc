# 09 Quality Requirements

## 1. 业务正确性

- `Step1` 必须可追溯当前 case 的代表节点、语义路口集合、道路集合、DriveZone、RCSDRoad 与 RCSDNode。
- `Step2` 只允许当前正式模板：`center_junction / single_sided_t_mouth`。
- `Step3` 必须保持冻结前置语义：道路归属、DriveZone 约束、邻近路口切断、foreign 屏蔽、foreign MST 补充切断、must-cover、single-sided opposite-side guard、no-silent-fallback。
- `Step4` 必须稳定解释 `A / B / C` 三类 RCSD 关联结果。
- `Step5` 必须区分正式 hard negative 对象与 audit-only foreign 对象。
- `Step6` 不得突破合法空间、directional boundary 或 excluded hard mask。
- `Step7` 机器状态只允许 `accepted / rejected`；批量运行另需显式区分 `runtime_failed`。

## 2. 输出与契约稳定性

- 可批量：Anchor61 必须按 `61 raw / 58 default formal` 稳定落盘。
- 可发布：`virtual_intersection_polygons.gpkg` 是 batch / full-input 正式聚合成果层。
- 可发布：`nodes.gpkg` 只能更新当前批次 selected / effective case 的代表 node `is_anchor`；`accepted => yes`、`rejected / runtime_failed => fail3`，非代表 node 与未选中 node 必须保持输入值不变。
- 可一致：`nodes_anchor_update_audit.csv / nodes_anchor_update_audit.json` 的行集、计数与 `nodes.gpkg` 实际写值必须一致。
- 可兼容：现有 `association_*` 与 `step7_*` 输出文件名继续作为当前兼容契约保留，不因文档主结构切换而重命名。

## 3. Review 与 formal 分层

- `V1~V5` 只属于视觉审计层，不等价于正式机器状态。
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
