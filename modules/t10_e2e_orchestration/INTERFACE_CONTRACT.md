# T10 - INTERFACE_CONTRACT

## 定位

本文件是 `t10_e2e_orchestration` 的稳定接口契约。

T10 面向 RCSD_Topo 端到端业务流程编排与 Case 级证据组织。项目级主业务链仍保持 `T08 -> T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09`；T10 v1 的局部编排范围为 `T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09`，T08 作为独立前置预处理、质检与修复模块，不由 T10 v1 调用。

## 1. 目标与范围

### 1.1 当前正式支持

- 固化 T10 v1 编排链路：
  - `T01`
  - `T07`
  - `T03`
  - `T04`
  - `T05`
  - `T06`
  - `T09`
- 为全链路建立显式文件级 handoff slot。
- 拒绝目录型 handoff，例如只传 `t05_phase2_root` 而不指明 `intersection_match_all.geojson / rcsdroad_out.gpkg / rcsdnode_out.gpkg`。
- 输出 T10 workflow plan、handoff audit 与 summary。
- 支持从 T10 Case package 启动 Case 级端到端执行：`T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09`。
- 支持输出 T10 Case run manifest、stage audit 与 T06 数据漏斗。
- 以 SWSD 语义路口 ID 和半径声明 Case 证据包范围。
- 支持 Case 候选建议：从 SWSD nodes 建立语义路口 inventory，再用可选 selector evidence 映射出问题候选。
- 支持多个 CaseID 一次打包，解包后按 `cases/<case_id>/` 重组。
- 支持文本 bundle 自动分片与解包。
- Case 证据包 v1 只纳入外部输入，排除模块间中间产物。
- `include_files=true` 时，正式默认物化模式为 `spatial_slice`：按 SWSD 语义路口 ID 与 `radius_m` 对外部输入生成局部 GPKG 切片。
- `spatial_slice` 必须补齐道路端点节点依赖，并保留被选中道路的完整几何，避免局部 Case replay 因窗口裁剪丢失 `snodeid/enodeid` 端点。

### 1.2 当前非目标

- 不改变项目级主业务链。
- 不调用 T08。
- 不修改 T01-T09 模块算法。
- 不新增 repo CLI、`Makefile` 目标、模块 `run.py` 或模块 `__main__.py`。
- root `scripts/t10_pack_innernet_cases.sh` 是当前正式内网 Case 证据包打包入口。
- root `scripts/t10_run_e2e_cases.sh` 是当前正式 T10 Case 级端到端执行入口。
- 不补充或改写 T09 业务实现；T09 模块文档面已由独立文档治理补齐。

## 2. Inputs

### 2.1 Workflow manifest

T10 v1 callable 接受一个结构化 manifest，至少包含：

```json
{
  "external_inputs": {
    "prepared_swsd_nodes": "...",
    "prepared_swsd_roads": "...",
    "drivezone": "...",
    "divstripzone": "...",
    "rcsd_intersection": "...",
    "rcsdroad": "...",
    "rcsdnode": "...",
    "sw_restriction_tool7": "...",
    "sw_arrow_tool8": "..."
  },
  "handoffs": {
    "t01_segment": "...",
    "t01_nodes": "...",
    "t01_roads": "...",
    "t07_nodes": "...",
    "t07_relation_evidence": "...",
    "t07_surface": "...",
    "t03_surface": "...",
    "t03_relation_evidence": "...",
    "t03_intersection_match": "...",
    "t04_surface": "...",
    "t04_relation_evidence": "...",
    "t04_intersection_match": "...",
    "t05_junction_surface": "...",
    "t05_intersection_match_all": "...",
    "t05_rcsdroad_out": "...",
    "t05_rcsdnode_out": "...",
    "t06_frcsd_road": "...",
    "t06_frcsd_node": "...",
    "t06_swsd_frcsd_segment_relation": "...",
    "t09_restored_field_rules": "..."
  }
}
```

### 2.2 Case package request

Case 证据包 v1 输入：

- `semantic_junction_id` / `semantic_junction_ids`：SWSD 语义路口 ID。CaseID 的正式含义是 SWSD semantic junction id，不是坐标。
- `radius_m`：Case 范围半径，单位米，当前切片 CRS 为 `EPSG:3857`。
- `include_files`：是否物化外部输入文件；`true` 时默认生成空间切片，`false` 时只生成 manifest。
- `materialization_mode`：可选，允许值：
  - `spatial_slice`：正式默认；生成局部 GPKG 切片。
  - `manifest_only`：只写 manifest，不扫描或复制全量输入内容。
  - `copy_full`：兼容诊断模式；复制全量外部输入，不作为正式内网 Case 包默认模式。

### 2.3 Case suggest request

`suggest` 的输入分两类：

- `prepared_swsd_nodes`：必选，用于建立 SWSD 语义路口 inventory。
- `selector_evidence`：可选，用于从 T08/T05/T06/T09 等审计或错误文件中筛出问题候选。

语义路口 inventory 规则：

- 若 node 有有效 `mainnodeid`，CaseID 使用 canonical `mainnodeid`。
- 若 `mainnodeid` 为空、`0`、`0.0`、`none`、`null`、`nan` 或 `-1`，CaseID 退化为 node `id`。
- 坐标只从 CaseID 对应 member node geometry 派生为 `center_x / center_y`，不作为 CaseID。

selector evidence 映射规则：

- 优先读取 `case_id / swsd_semantic_junction_id / semantic_junction_id / target_id / mainnodeid / junction_id / main_node_id`。
- 若上述字段不能直接命中 CaseID，再读取 `node_id / id` 并映射到该 node 所属 SWSD 语义路口。
- 命中 selector evidence 的 Case 输出 `candidate_status = problem_candidate`。
- 没有 selector evidence 时，可输出 `candidate_status = inventory_only` 的可打包语义路口清单，但不得表述为问题 Case。

### 2.4 Case runner request

T10 Case runner 输入：

- `package_dir`：已解包或直接生成的 T10 Case package 目录。支持多 Case package 根目录，也支持单 Case 目录。
- `case_id`：可选，可重复指定。未指定时执行 package 内全部 Case。
- `out_root`：T10 E2E run 输出根目录。
- `run_id`：可选。未指定时自动生成。
- `stop_after`：可选阶段名，用于受控截断执行。允许值为 `t01 / t07 / t03 / t04 / t05 / t06_step12 / t06_step3 / t09_step12 / t09_step3`。
- `continue_on_error`：是否在某个 Case 阶段失败后继续记录后续 Case 或后续阶段阻断状态。

Case runner 必须优先消费 Case package 中 `external_inputs/<slot>/<slot>_slice.gpkg`。当 package 仅为 manifest-only 时，才回退到 manifest 记录的 source path。

Case runner 不改变 T01-T09 算法，只负责：

- 把 T10 外部输入与模块间 handoff 显式绑定到文件路径。
- 调用已存在的模块脚本或模块 callable。
- 记录每个阶段的 command、env override、输入、输出、stdout log、耗时与状态。
- 在 T06 可执行时生成 T06 数据漏斗。

## 3. Outputs

### 3.1 Workflow planning outputs

目录：

```text
<out_root>/<run_id>/
```

文件：

- `t10_workflow_plan.json`
- `t10_handoff_audit.json`
- `t10_summary.json`

`t10_handoff_audit.json` 至少记录：

- 是否通过。
- 缺失 slot。
- 目录型 handoff。
- 严格存在性检查下的缺失文件。

### 3.2 Case evidence package outputs

单 Case 目录：

```text
<out_root>/<package_id>/
```

文件：

- `t10_case_evidence_manifest.json`
- `t10_case_evidence_summary.json`
- 可选：`external_inputs/<slot>/<source_file>`

Case package manifest 必须记录：

- SWSD 语义路口 ID。
- 半径、切片 CRS、中心点与 bounds。
- 所有外部输入 slot。
- 被排除的模块间 handoff slot。
- `selection_status`。`spatial_slice` 成功时为 `spatial_slice_completed`；manifest-only 时为 `manifest_scope_declared`。

`spatial_slice` 模式输出：

```text
external_inputs/<slot>/<slot>_slice.gpkg
```

每个 slot 的审计至少包含：

- source path、source exists、source size、source mtime。
- source feature count、selected feature count、output feature count。
- output path、output size、output sha256、output bounds。
- source CRS、CRS source、output CRS。
- invalid geometry count、empty-after-clip count。

多 Case 目录：

```text
<out_root>/<package_id>/
  t10_multi_case_evidence_manifest.json
  t10_multi_case_evidence_summary.json
  cases/
    <case_id>/
      t10_case_evidence_manifest.json
      t10_case_evidence_summary.json
      external_inputs/
```

文本 bundle 分片：

```text
t10_case_bundle.txt
t10_case_bundle.part_0002_of_000N.txt
...
```

解包时必须自动读取同目录其它分片，校验 checksum，并恢复 `cases/<case_id>/` 目录结构。

### 3.3 Case suggestion outputs

目录：

```text
<out_root>/<run_id>/
```

文件：

- `t10_case_suggestions.json`
- `t10_case_suggestions.csv`
- `t10_case_suggestions_summary.json`

### 3.4 Case runner outputs

目录：

```text
<out_root>/<run_id>/
```

文件：

- `t10_e2e_run_manifest.json`
- `t10_e2e_run_summary.json`
- `cases/<case_id>/t10_e2e_case_run_manifest.json`
- `cases/<case_id>/t10_e2e_case_run_summary.json`
- `cases/<case_id>/t10_t06_funnel.json`
- `cases/<case_id>/t10_t06_funnel.csv`
- `cases/<case_id>/t10_t06_funnel.md`
- `cases/<case_id>/<stage>/stdout.log`
- `cases/<case_id>/<stage>/<stage>_stage.json`

阶段状态：

- `passed`：阶段命令返回 0，且 T10 已记录该阶段可发现输出。
- `failed`：阶段命令返回非 0 或发生未捕获异常。
- `blocked`：阶段所需显式输入缺失，或同一 Case 的前置阶段未通过。
- `skipped`：执行策略导致阶段未运行。

同一 Case 内任一阶段 `failed/blocked` 后，T10 不提升该阶段的部分输出为正式 handoff，后续阶段只写 blocked 审计。`CONTINUE_ON_ERROR` 只控制多 Case 批处理是否继续执行下一个 Case。

T06 数据漏斗至少记录：

- Step1：`input_segment_count / evd_candidate_count / swsd_candidate_count / final_fusion_unit_count / swsd_final_fusion_unit_count`。
- Step2：`input_fusion_unit_count / rcsd_candidate_count / replaceable_count / rejected_count / buffer_segment_count / buffer_rejected_count`。
- Step3：`input_replaceable_count / replacement_unit_success_count / replacement_unit_failure_count / removed_swsd_road_count / removed_swsd_node_count / added_rcsd_road_count / added_rcsd_node_count / frcsd_road_count / frcsd_node_count / segment_relation_count`。
- 质量：Step1/Step2 reject reason、Step2 buffer reject reason、Step3 collision 与 segment relation 状态计数。

## 4. EntryPoints

当前 repo 官方入口：

```bash
bash scripts/t10_pack_innernet_cases.sh <case_id> [case_id ...]
bash scripts/t10_run_e2e_cases.sh --package-dir <decoded_or_generated_package_dir> [--case-id <case_id> ...]
```

该入口的 CaseID 含义固定为 SWSD semantic junction id。脚本读取 T10 v1 外部输入 slot，生成多 Case package，并导出可自动分片的文本 bundle。解包后目录结构按 `cases/<case_id>/` 恢复。

脚本支持的位置参数与环境变量：

- `CASE_IDS`：未提供位置参数时使用，支持逗号分隔。
- `RADIUS_M`：Case 范围半径，默认 `250`。
- `INCLUDE_FILES`：是否物化外部输入文件，默认 `1`。
- `MATERIALIZATION_MODE`：物化模式，默认按 `INCLUDE_FILES` 自动选择；`INCLUDE_FILES=1` 时默认 `spatial_slice`。
- `OUT_ROOT`：package 输出根目录，默认 `outputs/_work/t10_case_evidence`。
- `BUNDLE_ROOT`：文本 bundle 输出根目录，默认 `outputs/_work/t10_case_evidence_bundles`。
- `MAX_TEXT_SIZE_BYTES`：文本 bundle 分片阈值，默认 `256000`。
- `DECODE_AFTER_EXPORT`：是否导出后立即解包校验，默认 `0`。
- `TESTDATA_ROOT`：内网测试数据根目录，默认 `/mnt/d/TestData/POC_Data`。
- T10 v1 外部输入 slot 环境变量：`PREPARED_SWSD_NODES`、`PREPARED_SWSD_ROADS`、`DRIVEZONE`、`DIVSTRIPZONE`、`RCSD_INTERSECTION`、`RCSDROAD`、`RCSDNODE`、`SW_RESTRICTION_TOOL7`、`SW_ARROW_TOOL8`。

`scripts/t10_run_e2e_cases.sh` 支持的位置参数与环境变量：

- `--package-dir` / `PACKAGE_DIR`：T10 package 目录。
- `--case-id`：可重复指定。未指定时执行 package 内全部 Case。
- `OUT_ROOT`：T10 E2E 输出根目录，默认 `outputs/_work/t10_e2e_case_runs`。
- `RUN_ID`：可选输出 run id。
- `STOP_AFTER`：可选截断阶段。
- `CONTINUE_ON_ERROR`：默认 `1`；仅控制当前 Case 失败后是否继续下一个 Case，不允许同一 Case 下游消费失败阶段的部分输出。
- `EXIT_ZERO`：默认 `0`；置 `1` 时即使存在 blocked/failed Case 也返回 0，便于诊断批处理继续。
- `T10_T03_WORKERS`、`T10_T04_WORKERS`、`T10_T05_READONLY_WORKERS`：默认均为 `1`，用于 Case 级局部 replay。

当前仍无 repo CLI、`Makefile` 目标、模块 `run.py` 或模块 `__main__.py`。

可在测试或上层调用中使用模块内 callable：

```python
from rcsd_topo_poc.modules.t10_e2e_orchestration import (
    build_multi_case_evidence_package,
    build_case_evidence_package,
    build_t10_t06_funnel_summary,
    decode_t10_case_evidence_text_bundle,
    export_t10_case_evidence_text_bundle,
    run_t10_e2e_cases_from_package,
    suggest_t10_cases,
    write_t10_planning_outputs,
)
```

后续新增其它稳定入口必须另行授权并同步 `docs/repository-metadata/entrypoint-registry.md`。

## 5. Params

- `strict_exists`：是否要求 manifest 中配置的路径在本机存在。
- `run_id`：workflow planning 输出 run id；缺省自动生成。
- `package_id`：Case package id；缺省自动生成。
- `include_files`：是否物化外部输入文件。
- `materialization_mode`：`spatial_slice / manifest_only / copy_full`。
- `target_epsg`：空间切片目标 CRS，默认 `3857`。
- `selector_evidence`：用于 suggest 的候选证据文件映射。
- `max_text_size_bytes`：文本 bundle 自动分片阈值，默认 `250KB`。
- `stop_after`：T10 E2E Case runner 截断阶段。
- `continue_on_error`：T10 E2E Case runner 是否继续记录后续 Case 或阻断阶段。

## 6. Acceptance

1. T10 v1 workflow plan 中链路不包含 T08。
2. 项目级主业务链仍保留 T08。
3. 目录型 handoff 被审计为错误。
4. Case evidence package manifest 包含所有外部输入 slot。
5. Case evidence package manifest 排除 T01-T09 模块间中间产物。
6. `suggest` 只能把 selector evidence 映射为候选 Case，不把 inventory-only 清单表述为问题。
7. 多 Case bundle 解包后按 `cases/<case_id>/` 恢复目录。
8. 不新增未登记执行入口。
9. GIS / 拓扑 QA 五项在 summary 或模块质量文档中有明确状态。
10. `spatial_slice` 模式不得复制全量外部输入；每个 Case 目录只能物化半径窗口内的局部 GPKG。
11. `spatial_slice` 必须审计道路端点节点依赖完整性，不允许 silent fix。
12. Case runner 必须输出每阶段显式输入、输出、命令、状态与日志路径。
13. T06 已运行时必须输出 `t10_t06_funnel.json/csv/md`。
