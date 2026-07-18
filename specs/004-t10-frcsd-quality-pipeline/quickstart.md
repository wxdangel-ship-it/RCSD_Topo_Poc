# Quickstart: T10 FRCSD 质量检查专用流水线

在 WSL 中进入仓库后，显式提供原始 1V1 FRCSD 和既有 full runner 所需输入：

```bash
RUN_ID=t10_frcsd_quality_<timestamp> \
FRCSD_1V1_ROADS_PATH=/path/to/original_1v1_frcsd_roads.gpkg \
FRCSD_1V1_NODES_PATH=/path/to/original_1v1_frcsd_nodes.gpkg \
bash scripts/t10_run_frcsd_quality_pipeline.sh
```

脚本固定跳过 T08、启用 T12。不得把 T06 Step3 F-RCSD 作为 `FRCSD_1V1_*` target。

裁剪 Case 验收时额外传入 `T12_CASE_MANIFEST=/path/to/t10_case_evidence_manifest.json`；全图数据不传。
