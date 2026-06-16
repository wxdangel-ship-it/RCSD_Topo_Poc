# T10 端到端业务流程编排

> 本文件是 `t10_e2e_orchestration` 的操作者总览。长期源事实以 `architecture/*` 与 `INTERFACE_CONTRACT.md` 为准。

## 1. 模块定位

T10 用于组织 RCSD_Topo 端到端业务链路和 Case 级证据包。T10 v1 编排 `T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09`，T08 独立运行，不纳入 v1 编排步骤。

## 2. 运行入口

当前正式 root 脚本入口：

```bash
bash scripts/t10_pack_innernet_cases.sh 991176 74155468
bash scripts/t10_run_e2e_cases.sh --package-dir outputs/_work/t10_case_evidence/<package_id>
bash scripts/t10_run_innernet_full_pipeline.sh
```

脚本支持多个 SWSD semantic junction id，一次生成多 Case package，并导出自动分片的文本 bundle。`INCLUDE_FILES=1` 时默认按 `semantic_junction_id + RADIUS_M` 生成局部 GPKG 空间切片，不复制全量外部输入。默认内网数据根目录为 `/mnt/d/TestData/POC_Data`，也可通过 `PREPARED_SWSD_NODES`、`PREPARED_SWSD_ROADS`、`DRIVEZONE`、`DIVSTRIPZONE`、`RCSD_INTERSECTION`、`RCSDROAD`、`RCSDNODE`、`SW_RESTRICTION_TOOL7`、`SW_ARROW_TOOL8` 显式覆盖输入。

`scripts/t10_run_e2e_cases.sh` 从已生成或已解包的 T10 Case package 启动 Case 级全链路执行。它按 `T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09` 调用既有脚本或模块 callable，输出每阶段日志、handoff 审计和 `t10_t06_funnel.json/csv/md`。T08 仍是独立前置预处理和质量修复模块，不由该 runner 调用。

当需要验证 T06 上游反馈闭环时，可设置 `T10_FEEDBACK_ITERATIONS=1`。runner 会先执行 baseline pass，发布 `t10_upstream_side_group_endpoint_candidates.csv/json`，再把该 endpoint 级候选作为 T05 Phase2 可选输入执行下一 pass。顶层 summary 会比较 baseline 与最终 pass 的 replacement plan 和 Step3 replaced Segment；若已有 replaced Segment 被移除，`feedback_regression_guard_passed = false` 且本次 run 不通过。

`scripts/t10_run_innernet_full_pipeline.sh` 是内网全量数据总控入口，不消费 Case package。它以 `/mnt/d/TestData/POC_Data` 为默认数据根目录，按 `T08 -> T01 -> T07 Step1/2 -> T03 -> T04 -> T05 -> T07 Step3 -> T06 Step1/2 -> T06 Step3 -> T09` 串联已有模块脚本或 callable，并把所有阶段输出写入 `outputs/_work/t10_innernet_full_pipeline/<RUN_ID>/`。该脚本只负责全量 handoff 编排和审计 manifest，不改变 T01-T09 模块算法。

同一 Case 内任一阶段未通过时，runner 不把该阶段部分输出提升为正式 handoff；后续阶段标记为 `blocked`。`CONTINUE_ON_ERROR=1` 只表示批处理继续下一个 Case。

模块同时提供 callable：

```python
from rcsd_topo_poc.modules.t10_e2e_orchestration import (
    build_case_evidence_package,
    run_t10_e2e_cases_from_package,
    write_t10_planning_outputs,
)
```

## 3. 常见运行方式

- 使用 `write_t10_planning_outputs` 生成 workflow plan、handoff audit 与 summary。
- 使用 `suggest_t10_cases` 从 SWSD nodes 与可选 selector evidence 生成候选 Case 列表。
- 使用 `build_case_evidence_package` 生成 Case 证据包；`include_files=True` 默认生成空间切片。
- 使用 `build_multi_case_evidence_package` 一次打包多个 SWSD 语义路口 ID。
- 使用 `export_t10_case_evidence_text_bundle` / `decode_t10_case_evidence_text_bundle` 分片传输并解包恢复 `cases/<case_id>/` 结构。
- 使用 `run_t10_e2e_cases_from_package` 从 Case package 执行端到端 Case replay。
- 内网正式打包入口使用 `scripts/t10_pack_innernet_cases.sh`；`examples/t10_pack_innernet_cases.sh` 仅保留为历史示例。
- 内网正式 Case 级执行入口使用 `scripts/t10_run_e2e_cases.sh`。
- 内网正式全量执行入口使用 `scripts/t10_run_innernet_full_pipeline.sh`。

## 4. 输出总览

- `t10_workflow_plan.json`
- `t10_handoff_audit.json`
- `t10_summary.json`
- `t10_case_suggestions.json/csv`
- `t10_case_evidence_manifest.json`
- `t10_case_evidence_summary.json`
- `external_inputs/<slot>/<slot>_slice.gpkg`
- `t10_multi_case_evidence_manifest.json`
- `t10_multi_case_evidence_summary.json`
- `t10_e2e_run_manifest.json`
- `t10_e2e_run_summary.json`
- `t10_upstream_feedback_segments.csv/json`
- `t10_upstream_feedback_summary.csv/json`
- `t10_upstream_side_group_candidates.csv/json`
- `t10_upstream_side_group_endpoint_candidates.csv/json`
- `t10_upstream_pair_anchor_endpoint_clusters.csv/json`
- `t10_upstream_feedback_relations.csv/json`
- `t10_upstream_feedback_relation_summary.csv/json`
- `iterations/iteration_<NN>_<role>/t10_e2e_run_manifest.json`
- `iterations/iteration_<NN>_<role>/t10_e2e_run_summary.json`
- `t10_innernet_full_pipeline_manifest.json`
- `cases/<case_id>/t10_e2e_case_run_manifest.json`
- `cases/<case_id>/t10_t06_funnel.json/csv/md`

## 5. 文档阅读顺序

1. `INTERFACE_CONTRACT.md`
2. `architecture/01-introduction-and-goals.md`
3. `architecture/03-context-and-scope.md`
4. `architecture/04-solution-strategy.md`
5. `architecture/10-quality-requirements.md`

## 6. Innernet Manifest

`t10_innernet_full_pipeline_manifest.json` 同时保留 flat `inputs / outputs` 和阶段级 `stage_order / stages`。审计与下游消费应优先使用 `stages.<stage_id>.inputs / outputs / execution_context` 判断模块 handoff，避免根据目录名猜测产物角色。
