# Pipeline Contract: T10 FRCSD Quality Profile

## 正式入口

```bash
RUN_ID=<unique_run_id> \
SWSD_INPUT_NODES=<prepared_swsd_nodes.gpkg> \
SWSD_INPUT_ROADS=<prepared_swsd_roads.gpkg> \
FRCSD_1V1_ROADS_PATH=<original_1v1_frcsd_roads.gpkg> \
FRCSD_1V1_NODES_PATH=<original_1v1_frcsd_nodes.gpkg> \
bash scripts/t10_run_frcsd_quality_pipeline.sh
```

可选 `T12_REVIEW_DECISIONS=<review.csv>`。裁剪 Case 验收可显式提供 `T12_CASE_MANIFEST=<t10_case_evidence_manifest.json>` 以排除裁剪边界；全图运行留空。其余 RCSDIntersection、RCSD、DriveZone 和 T09 输入沿用 full runner 显式环境变量合同。

## 固定 profile

- `RUN_T08=0`
- `RUN_T12=1`
- stage：`t01,t07_step12,t03,t04,t05,t06_step12,t06_step3,t11,t12,t09`
- T11/T12 均为 audit-only；T09 继续消费 T06。

## 输出

沿用 `t10_run_innernet_full_pipeline.sh` 的 run root、manifest 和 summary；专用入口默认输出父目录为 `outputs/_work/t10_frcsd_quality_pipeline`。
