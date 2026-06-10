# T10 Case 空间切片证据包实施计划

## 1. 实施策略

1. 复用 T08 `vector_io` 完成矢量读写与 CRS 归一。
2. 参考 T06/T09 文本包的窗口选择与 QA summary 结构。
3. 用 T10 自身的 `prepared_swsd_nodes` inventory 规则定位 Case member nodes。
4. 输出仍保持 T10 既有 `cases/<case_id>/` 结构。

## 2. 写集

- `specs/t10-spatial-case-slicing/*`
- `src/rcsd_topo_poc/modules/t10_e2e_orchestration/spatial_slice.py`
- `src/rcsd_topo_poc/modules/t10_e2e_orchestration/evidence_package.py`
- `src/rcsd_topo_poc/modules/t10_e2e_orchestration/__init__.py`
- `scripts/t10_pack_innernet_cases.sh`
- `modules/t10_e2e_orchestration/INTERFACE_CONTRACT.md`
- `modules/t10_e2e_orchestration/README.md`
- `modules/t10_e2e_orchestration/architecture/*`
- `tests/modules/t10_e2e_orchestration/test_t10_contracts.py`

不新增新的正式入口，不修改入口 registry。

## 3. 关键设计

- `materialization_mode="spatial_slice"`：正式默认，`include_files=True` 时写局部 GPKG。
- `materialization_mode="copy_full"`：兼容旧行为，仅诊断使用。
- `materialization_mode="manifest_only"`：不写矢量文件。
- 每个 output GPKG 用 slot 命名：`external_inputs/<slot>/<slot>_slice.gpkg`。
- 每个 Case summary 汇总 slot selected counts 与 QA。

## 4. 验证

- `.venv/bin/python -m pytest tests/modules/t10_e2e_orchestration`
- `bash -n scripts/t10_pack_innernet_cases.sh`
- `git diff --check`
- 文件体量检查：新增 / 修改 `.py`、`.sh` 均小于 100KB。
