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
| `t10_multi_segment_evidence_manifest.json` | 多 Segment package 顶层清单、SegmentID、T10 run root 和各 Segment 目录。 |
| `external_inputs/<slot>/<slot>_slice.gpkg` | Case replay 使用的局部输入切片。 |
| text bundle 分片 | 内外网传输和解包恢复 Case package。 |

Segment package 的 `t10_case_evidence_manifest.json` 必须额外记录 `scope.scope_type=swsd_segment`、`scope.swsd_segment_id`、T01 `segment.gpkg` 来源、匹配到的 T06 evidence rows 和 evidence artifact 路径。T10/T06 中间产物只作为 evidence reference，不复制到 package payload。

## 3. Case Runner 证据

每个 Case 每个阶段都必须记录 command、env override、输入、输出、stdout log、耗时和状态。失败阶段的部分输出不提升为正式 handoff；后续阶段应标记 blocked。

T11 stage 必须记录当前 Case root、关键 T06 Step3 文件、实际 `run_root`、candidates CSV/GPKG、人工模板与 summary。T11 summary 中的 discovered inputs 是完整文件级输入审计；T11 失败时 T09 必须 blocked。

T12 stage 只在显式启用时存在，必须记录原始 1V1 F-RCSD、SWSD、RCSDIntersection、T05 audit、T06 交叉证据、参数、CRS、运行环境、耗时和全部发布路径。候选、confirmed、excluded、manual review 必须分层；没有 review decisions 时由自动高置信规则发布 confirmed/excluded，默认 manual 为 0，外部 review decisions 仅作为可选决定覆盖。

## 4. T06 证据

`t10_t06_funnel.*` 读取 T06 Step1 / Step2 / Step3 summary 和输出，解释数量流转；其 Step1 分母必须来自 `final_swsd_nodes`，不能回退到 T07 Step2 nodes。`t10_t06_visual_check_summary.*` 默认索引 T01 Segment/Road、T07 Step2、T03/T04/T05 surface、T06 replacement plan / problem registry、F-RCSD、relation、topology connectivity audit 和 surface topology audit；只有显式运行 T07 Step3 时，才额外记录 Step3 补锚图层。

## 5. Feedback 证据

T10 upstream feedback 从 T06 problem registry、repair candidates、relation audit 和 replacement plan 中提炼 Segment、relation、side-group endpoint 和 pair-anchor endpoint cluster 视图。feedback 必须带来源文件和 case/run 路径，不直接驱动 Step3 替换。

## 6. Full Pipeline 证据

`t10_innernet_full_pipeline_manifest.json` 记录 `stage_order / stages / inputs / outputs / execution_context`，其中 `t11` 固定位于 `t06_step3` 后；启用 T12 时顺序固定为 `t06_step3 -> t11 -> t12 -> t09`。当 profile 固定 `RUN_T08=0` 时，manifest 不登记未运行的 T08 stage。`t10_innernet_full_pipeline_summary.json` 是轻量完成判定文件，内网监控应优先读取其中 `status / passed / finished_at_utc / duration_seconds` 及已启用审计阶段的必要产物。
