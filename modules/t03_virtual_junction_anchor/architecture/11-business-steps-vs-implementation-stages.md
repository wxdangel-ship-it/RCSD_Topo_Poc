# 11 Business Steps vs Implementation Stages

本文档用于把当前正式业务步骤与历史实现阶段清楚分层。它不新增运行入口，不改变输出文件名，也不要求重命名现有代码符号。

## 1. 正式业务主链

T03 当前正式业务主链固定按 `Step1~Step7` 理解：

| 正式步骤 | 业务职责 | 当前主要实现位置 |
|---|---|---|
| `Step1` | 当前 case 受理、代表节点与局部上下文建立 | `association_loader.py`、`full_input_case_pipeline.py`、`full_input_shared_layers.py` |
| `Step2` | 模板归类，只接收当前正式支持的模板 | `association_loader.py`、`association_models.py` |
| `Step3` | 合法活动空间冻结，并提供不可反向篡改的前置约束 | `step3_engine.py`、`legal_space_outputs.py`、`legal_space_render.py` |
| `Step4` | RCSD 关联语义识别，形成 `A / B / C` 关联解释 | `step4_association.py`、`association_models.py` |
| `Step5` | foreign / excluded 负向约束分组与审计 | `step5_foreign_filter.py`、`association_outputs.py` |
| `Step6` | 在冻结空间、RCSD 关联和负向约束下生成受约束几何 | `step6_geometry.py`、`finalization_outputs.py` |
| `Step7` | 最终 `accepted / rejected` 判定、发布与 batch closeout | `step7_acceptance.py`、`t03_batch_closeout.py`、`finalization_outputs.py` |

## 2. 历史实现阶段

`Step45` 与 `Step67` 是历史实现阶段名，不再作为正式需求主结构。

| 历史标签 | 当前解释 | 允许出现的位置 |
|---|---|---|
| `Step45` | `Step4 + Step5` 的历史联合实现阶段，承载 RCSD 关联、`required / support / excluded` 分类、状态与审计文件 | 现有 CLI 名、代码类名、输出文件名、测试、历史 closeout、兼容说明 |
| `Step67` | `Step6 + Step7` 的历史 finalization / delivery 阶段，承载受约束几何、最终发布、review PNG 与 batch closeout | 现有代码类名、输出文件名、测试、历史 closeout、兼容脚本、兼容说明 |

## 3. 命名保留原则

- 现有 `step45_*` 与 `step67_*` 文件名是当前输出兼容契约的一部分，本轮不重命名。
- 现有 `Step45Context / Step45CaseResult / Step67Context / Step67CaseResult` 等代码符号是当前实现 API，本轮不重命名。
- 现有 `t03-step45-rcsd-association` CLI 是 repo 官方入口事实，本轮不删除、不改签名。
- 现有 `t03_run_step67_internal_full_input_8workers.sh` 与 `t03_watch_step67_internal_full_input.sh` 是历史兼容 wrapper，本轮不退役。
- 新文档主叙述不再用 `Step45 / Step67` 组织业务章节；需要解释历史命名时，应引用本映射文档。

## 4. 审计与验收口径

- 正式状态以 `Step7` 机器状态为准：`accepted / rejected`；批量运行还需区分 `runtime_failed`。
- 视觉等级 `V1~V5` 只属于 review-only 层，不得反向覆盖正式状态。
- `virtual_intersection_polygons.gpkg`、`nodes.gpkg` 与 `nodes_anchor_update_audit.*` 是 batch / full-input 正式成果。
- `step67_review.png`、`t03_review_*` 与 `visual_checks/` 是 review-only 产物。
- `terminal_case_records/<case_id>.json` 是 internal full-input 的 authoritative terminal state；`t03_streamed_case_results.jsonl` 是 append log，不作为唯一准真值。
