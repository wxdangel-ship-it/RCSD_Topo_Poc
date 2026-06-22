# 04 证据与审计

## 1. 审计目标

T10 必须让端到端运行可以回答：用了哪些外部输入、每个模块收到什么文件、产出了什么文件、失败在哪里、T06 替换漏斗如何变化、哪些问题应回流上游、人工该看哪些图层。

## 2. Workflow 与 Case Package 证据

| 证据 | 业务用途 |
|---|---|
| `t10_workflow_plan.json` | 外部输入和 handoff slot 规划。 |
| `t10_handoff_audit.json` | 缺失、目录型 handoff 和文件存在性审计。 |
| `t10_case_evidence_manifest.json` | Case 范围、输入 slot、切片状态和 excluded handoff。 |
| `t10_case_evidence_summary.json` | Case package 计数、输入、bounds 和状态。 |
| `external_inputs/<slot>/<slot>_slice.gpkg` | Case replay 使用的局部输入切片。 |
| text bundle 分片 | 内外网传输和解包恢复 Case package。 |

## 3. Case Runner 证据

每个 Case 每个阶段都必须记录 command、env override、输入、输出、stdout log、耗时和状态。失败阶段的部分输出不提升为正式 handoff；后续阶段应标记 blocked。

## 4. T06 证据

`t10_t06_funnel.*` 读取 T06 Step1 / Step2 / Step3 summary 和输出，解释数量流转。`t10_t06_visual_check_summary.*` 索引 T01 Segment/Road、T07 Step3、T03/T04/T05 surface、T06 replacement plan / problem registry、F-RCSD、relation、topology connectivity audit 和 surface topology audit。

## 5. Feedback 证据

T10 upstream feedback 从 T06 problem registry、repair candidates、relation audit 和 replacement plan 中提炼 Segment、relation、side-group endpoint 和 pair-anchor endpoint cluster 视图。feedback 必须带来源文件和 case/run 路径，不直接驱动 Step3 替换。

## 6. Full Pipeline 证据

`t10_innernet_full_pipeline_manifest.json` 记录 `stage_order / stages / inputs / outputs / execution_context`。`t10_innernet_full_pipeline_summary.json` 是轻量完成判定文件，内网监控应优先读取其中 `status / passed / finished_at_utc / duration_seconds`。
