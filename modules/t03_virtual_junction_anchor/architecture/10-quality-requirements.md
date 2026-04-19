# 10 Quality Requirements

- 可审计：每个 case 都有 status、audit、PNG，且 Step45 与 Step67 的机器状态、视觉审计状态可分层回读
- 可批量：Anchor61 必须按 `61 raw / 58 default formal` 稳定落盘
- 可发布：`Step7` 机器状态只允许 `accepted / rejected`
- 可复核：`V1-V5` 继续保留为视觉审计层，且平铺目录与索引可供人工翻阅
- 可诊断：`review / not_established / rejected` 必须给出显式原因与根因分型
- 可回归：`virtual_intersection_polygons.gpkg` 的字段集合与字段槽位语义必须持续对齐 T02 Stage3 official full-input 当前实际聚合层实现；若 T02/T03 实现出现 schema 差异，必须显式登记 gap，不得静默漂移
- 可回归：`nodes.gpkg` 只能更新当前批次 selected / effective case 的代表 node `is_anchor`；`accepted => yes`、`rejected / runtime_failed => fail3`，非代表 node 与未选中 node 必须保持输入值不变
- 可一致：`nodes_anchor_update_audit.csv / nodes_anchor_update_audit.json` 的行集、计数与 `nodes.gpkg` 实际写值必须一致，且 batch aggregate polygon 上的 review 兼容字段不得反向渗透回 formal status / summary 面
- 可监控：`scripts/t03_watch_internal_full_input.sh` 默认只展示 `total / completed / running / pending / success / failed`；`DEBUG_VISUAL=1` 之外不得把 `V1-V5` 统计重新混入默认 formal monitor
- 可减载：`t03_internal_full_input_manifest.json` 与 `t03_internal_full_input_progress.json / t03_internal_full_input_performance.json` 必须保持 static-vs-runtime 分层；高频 runtime 文件不得重写 selected/discovered 全量 case id 列表
- 可稳态：高频 observability JSON 写盘必须使用 atomic rename；early failure 时至少能读到 progress/failure 工件，不能只留下空 run 目录
- 可量化：`candidate_discovery / shared_preload / local_feature_selection / step3 / step45 / step6 / step7 / output_write / visual_copy / observability_write` 分段耗时必须可回读，用于后续性能减压
- 可治理：模块文档面、项目级盘点、官方入口事实与当前实现保持一致
- 可克制：不把 solver 常量、启发式参数或单轮 closeout 结果误写成长期业务契约
