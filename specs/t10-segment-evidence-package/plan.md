# T10 Segment 级证据包实施计划

## 1. 实施策略

1. 保持现有 semantic junction Case package 不变。
2. 在 T10 内新增 Segment scope：以 T01 `segment.gpkg` 中的目标 Segment 几何和 matched T06 evidence rows 作为 spatial slice 证据闭包来源。
3. 从既有 T10 run root 读取 manifest、visual check、T06 problem registry / replacement plan / relation 等证据，写入 Segment package manifest 的 evidence references。
4. 复用现有 external input slot、spatial slice、text bundle 和 T10 Case runner。
5. 新增正式 root script，入口登记同步到 registry。

## 2. 写集

- `specs/t10-segment-evidence-package/*`
- `src/rcsd_topo_poc/modules/t10_e2e_orchestration/segment_package.py`
- `src/rcsd_topo_poc/modules/t10_e2e_orchestration/spatial_slice.py`
- `src/rcsd_topo_poc/modules/t10_e2e_orchestration/__init__.py`
- `scripts/t10_pack_innernet_segments.sh`
- `modules/t10_e2e_orchestration/SPEC.md`
- `modules/t10_e2e_orchestration/INTERFACE_CONTRACT.md`
- `modules/t10_e2e_orchestration/README.md`
- `modules/t10_e2e_orchestration/architecture/02-data-and-domain-model.md`
- `modules/t10_e2e_orchestration/architecture/04-evidence-and-audit.md`
- `modules/t10_e2e_orchestration/architecture/05-quality-requirements.md`
- `docs/repository-metadata/entrypoint-registry.md`
- `tests/modules/t10_e2e_orchestration/test_t10_contracts.py`

## 3. 关键设计

- Segment CaseID：`segment_<safe_segment_id>`，用于兼容现有 package runner 的 `cases/<case_id>/` 结构。
- 正式 Segment 身份字段：`scope.swsd_segment_id`。
- Segment scope 类型：`scope.scope_type = swsd_segment`。
- Segment evidence source：`t10_run_root` + `t01_segment` + T06 evidence artifacts。
- Segment external input selection：由 T01 Segment 几何、Segment 端点和 matched T06 evidence rows 中的 SWSD/RCSD 节点/道路依赖形成 evidence dependency closure，不暴露 `RADIUS_M`。
- 默认物化模式：`spatial_slice`。
- 外部输入仍按 `external_inputs/<slot>/<slot>_slice.gpkg` 输出。
- 多 Segment 包输出：

```text
<out_root>/<package_id>/
  t10_multi_segment_evidence_manifest.json
  t10_multi_segment_evidence_summary.json
  cases/
    segment_<segment_id>/
      t10_case_evidence_manifest.json
      t10_case_evidence_summary.json
      external_inputs/
```

## 4. 验证

- `.venv/bin/python -m pytest tests/modules/t10_e2e_orchestration`
- `bash -n scripts/t10_pack_innernet_segments.sh`
- `bash -n scripts/t10_pack_innernet_cases.sh`
- `git diff --check`
- 文件体量检查：新增 / 修改 `.py`、`.sh` 均小于 100KB。
- 1885118 本地验证：
  - 从既有 T10/T06 结果抽样有证据但未替换成功的 Segment。
  - 执行 Segment package 打包。
  - 解包或直接运行 `scripts/t10_run_e2e_cases.sh`，至少验证到可启动本地 T10 replay，并记录最终 passed / failed / blocked 状态及原因。
