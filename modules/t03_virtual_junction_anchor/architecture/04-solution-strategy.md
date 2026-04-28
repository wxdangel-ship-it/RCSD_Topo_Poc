# 04 Solution Strategy

## 1. 策略总览

T03 当前处理策略按正式业务主链 `Step1~Step7` 组织：

1. 建立当前 case 的代表节点、局部道路、DriveZone、RCSDRoad、RCSDNode 与冻结前置上下文。
2. 将 case 限定到当前正式支持模板：`center_junction` 或 `single_sided_t_mouth`。
3. 使用冻结合法空间作为不可反向篡改的前置约束。
4. 识别当前语义路口与 RCSD 的 `A / B / C` 关联关系。
5. 将不应进入当前路口面的 RCSD 对象分为 `excluded` 或 audit-only foreign。
6. 在合法空间、方向边界、required RC 与 hard negative mask 约束下生成最终候选几何。
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
- `Step5` 的 hard negative mask 当前仅由 `excluded_rcsdroad -> road-like 1m mask` 进入 `Step6`。
- `Step6` 必须在 directional boundary 内构面，不允许为满足 required RC 而突破边界。
- `Step7` 只发布 `accepted / rejected`；`V1~V5` 只属于 review-only 层。
- 对 `single_sided_t_mouth + association_class=A`，横方向口门按“竖向 RCSDRoad seed -> 横向 tracing -> terminal RCSDNode -> +5m -> stop at next directly-associated semantic junction”求解；无法确认横向两侧 terminal 时回到 generic directional boundary。
- 对冻结 `Step3` 已应用 `two_node_t_bridge` 的 case，后续几何必须继承该中心桥接支撑，不能由横向裁剪引入中心断开或桥位空洞。

## 6. 性能与观测策略

- shared-layer 查询使用空间索引与缓存，不回退到全层线性扫描。
- root progress / performance 文件受 flush gate 控制，避免每 case 高频重写。
- case-level terminal record 使用 atomic write。
- perf audit 继续记录 `candidate_discovery / shared_preload / local_feature_selection / step3 / step4 / step5 / step6 / step7 / output_write / observability_write` 等阶段耗时。
- review PNG 在 production no-debug 路径默认关闭；开启 review 时仍保持现有平铺输出契约。
