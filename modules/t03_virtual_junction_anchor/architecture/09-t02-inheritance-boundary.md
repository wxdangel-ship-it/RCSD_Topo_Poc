# 09 T02 Stage3 继承边界

## 1. 文档定位

- 本文用于明确：T03 internal full-input / Step67 正式交付与 T02 Stage3 official full-input 之间，哪些语义是继承复用，哪些不是。
- 它是 T03 模块级 source-of-truth 的边界说明，不回写 T02 上游正式契约。

## 2. T03 当前明确继承的内容

- full-input public env surface
  - repo 级 shell 包装脚本继续沿用 T02 风格的输入路径、`OUT_ROOT / RUN_ID / WORKERS / MAX_CASES / DEBUG_FLAG / VISUAL_CHECK_DIR` 等外显参数面
  - watch 脚本继续维持 formal-first 的默认使用习惯
- batch aggregate polygon schema
  - `virtual_intersection_polygons.gpkg` 字段集合与字段槽位语义对齐 T02 Stage3 official full-input 当前实际聚合成果层实现
  - batch aggregate layer 允许保留 `visual_review_class / official_review_eligible / failure_bucket` 等兼容字段，但仅限该聚合层
- official review helper / acceptance 槽位语义
  - `kind / kind_source`
  - `business_outcome_class / acceptance_class`
  - `official_review_eligible / failure_bucket`
- shared full-input / per-case local context 的总体思想
  - 先做 full-input candidate discovery
  - 共享读入全量图层
  - 再按单 case 局部窗口执行正式链路

## 3. T03 当前明确不继承的内容

- 不逐值复用 T02 Stage3 的状态值域
  - `virtual_intersection_polygons.gpkg` 的字段槽位继承 T02
  - 但 `status / business_outcome_class / acceptance_class / visual_review_class` 的实际写值来源于 T03 当前 `Step67` 结果，而不是 T02 Stage3 逐值照搬
- 不回写 T02 上游正式契约
  - `fail3` 只属于 T03 下游 `nodes.gpkg` 输出语义
  - 不修改 T02 `is_anchor` 既有值域契约
- 不把 T02 Stage3 单 case / full-input 全部内部工件逐一照搬
  - T03 只保留当前执行/监控所需的 internal manifest、runtime counters、performance、case progress 与 visual flat mirror
  - 不要求复制 T02 历史批次中的所有中间目录和旧式 pending 预写模式
- T03 当前没有 repo 官方 Step67 CLI
  - 当前 repo 官方 CLI 仍是 `t03-step45-rcsd-association`
  - Step67 通过模块内 batch runner 与 repo shell/watch 外壳维持正式交付

## 4. T03 当前自有语义

- formal stage 边界
  - T03 当前正式范围是冻结 `Step3 legal-space baseline` 之上的 `Step45 / Step67 clarified formal stage`
  - `Step6 / Step7` 是 T03 自有的 formal 结果层，不等价于 T02 Stage3 的阶段命名与实现拆分
- updated `nodes.gpkg` downstream 语义
  - 只更新当前批次 selected / effective case 的代表 node
  - `accepted => yes`
  - `rejected / runtime_failed => fail3`
  - 非代表 node 与未选中 node 保持输入值不变
- formal vs review 分层
  - `step7_status.json`、`step67_final_polygon.gpkg`、正式 `summary.json` 不承载 `visual_* / manual_review_*`
  - review-only 统计只留在 `t03_review_*`、`visual_checks/` 与 batch aggregate compatibility 字段
- observability / performance 语义
  - `t03_internal_full_input_manifest.json` 承载 static manifest
  - `t03_internal_full_input_progress.json` 承载 lightweight runtime counters
  - `t03_internal_full_input_performance.json` 承载 stage timer 与运行速率

## 5. 使用原则

- 需要说明“为什么 T03 看起来像 T02”时，优先引用本文而不是口头默认“完全继承”。
- 需要新增 T03 full-input 输出或监控语义时，先判断它属于：
  - T02 兼容槽位继承
  - T03 自有下游语义
  - review-only 辅助面
- 若未来 T02 Stage3 实现发生字段级变化，T03 必须重新做 field parity 核对；在确认前不得静默宣称“自动继承最新 T02”。
