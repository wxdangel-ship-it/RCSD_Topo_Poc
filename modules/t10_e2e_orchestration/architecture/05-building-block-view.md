# 05 Building Block View

## 1. contracts

`contracts.py` 定义：

- T10 v1 chain。
- T08 policy。
- 外部输入 slot。
- 模块间 handoff slot。
- workflow step spec。
- 目录型 handoff 禁止清单。

## 2. orchestrator

`orchestrator.py` 提供：

- `build_workflow_plan`
- `validate_t10_manifest`
- `write_t10_planning_outputs`

当前只做 contract validation，不执行 T01-T09 runner。

## 3. evidence_package

`evidence_package.py` 提供：

- `build_case_evidence_package`
- `build_multi_case_evidence_package`

当前生成 Case package manifest 与 summary，`include_files=true` 时默认调用空间切片能力物化局部外部输入。

## 4. spatial_slice

`spatial_slice.py` 提供：

- `build_case_spatial_input_slices`

当前按 SWSD semantic junction id 定位 member nodes，使用 `radius_m` 在 `EPSG:3857` 下生成窗口，并把外部输入 slot 写成局部 GPKG。

## 5. case_suggest

`case_suggest.py` 提供：

- `suggest_t10_cases`
- `write_t10_case_suggestions`

当前从 SWSD nodes 建立语义路口 inventory，并把 selector evidence 映射到候选 Case。

## 6. text_bundle

`text_bundle.py` 提供：

- `export_t10_case_evidence_text_bundle`
- `decode_t10_case_evidence_text_bundle`

当前以 zip + base85 文本容器传输 Case 包，超过阈值自动分片，解包后恢复原目录结构。
