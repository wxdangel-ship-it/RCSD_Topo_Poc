# 1885118 Segment 级证据包验证记录

**验证日期**：2026-06-30
**验证范围**：T10 Segment package 打包、文本分片、解包、本地 T10 replay。
**契约版本**：Segment geometry `200m` buffer；多 Segment 解包目录为 `<SegmentID>/` 一级目录。
**状态**：通过。1885118 抽样 3 个 Segment 的打包、分片、解包和本地 T10 replay 均通过。

## 1. 验证输入

- T10 run root：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_all_cases_c5085f0_20260630_181345/e2e_full/cases/1885118`
- T01 Segment：`/mnt/e/Work/RCSD_Topo_Poc/outputs/baselines/t10_all_cases_c5085f0_20260630_181345/e2e_full/cases/1885118/t01/segment.gpkg`
- external input：`/mnt/e/TestData/POC_Data/T10/1885118/external_inputs/<slot>/<slot>_slice.gpkg`
- 抽样 Segment：
  - `924076_14313744`
  - `1534342_62397379`
  - `1537607_512643052`

本验证使用当前本机可访问的既有 T10/T06 输出和外部输入切片；未声明或执行内网环境操作。

## 2. 打包与解包

- package 目录：`outputs/_work/t10_segment_evidence_verify_1885118_buffer200/packages/t10_segments_1885118_buffer200_20260630`
- decoded 目录：`outputs/_work/t10_segment_evidence_verify_1885118_buffer200/decoded/t10_segments_1885118_buffer200_20260630`
- bundle：
  - `outputs/_work/t10_segment_evidence_verify_1885118_buffer200/bundles/t10_segments_1885118_buffer200_20260630.txt`
  - `outputs/_work/t10_segment_evidence_verify_1885118_buffer200/bundles/t10_segments_1885118_buffer200_20260630.part_0002_of_0002.txt`
- `segment_buffer_m = 200.0`
- `selection_mode = swsd_segment_geometry_buffer`
- 顶层无 `cases/` 目录；解包后存在：
  - `924076_14313744/t10_case_evidence_manifest.json`
  - `1534342_62397379/t10_case_evidence_manifest.json`
  - `1537607_512643052/t10_case_evidence_manifest.json`

打包 summary：

| 指标 | 值 |
|---|---:|
| `passed` | `true` |
| `segment_count` | 3 |
| `failed_segment_count` | 0 |
| `materialization_mode` | `spatial_slice` |
| `materialized_file_count` | 27 |
| `matched_evidence_artifact_count` | 32 |

## 3. 本地 Replay

- replay run root：`outputs/_work/t10_segment_evidence_verify_1885118_buffer200/e2e_runs/t10_segments_1885118_buffer200_replay_20260630`
- `status = passed`
- `passed = true`
- `case_count = 3`
- `completed_case_count = 3`
- `passed_case_count = 3`
- `failed_case_count = 0`
- `blocked_case_count = 0`
- `duration_seconds = 422.61388`
- `t06_visual_check_case_count = 3`
- `upstream_feedback_segment_count = 6`

| CaseID | replay status | no-candidate handoff | Step2 replaceable | Step3 replacement success |
|---|---|---|---:|---:|
| `segment_1534342_62397379` | passed | none | 3 | 3 |
| `segment_1537607_512643052` | passed | `t04` / `no_eligible_candidates_in_segment_geometry_buffer` | 0 | 0 |
| `segment_924076_14313744` | passed | none | 3 | 1 |

T06 visual check 三行均为：

- `status = passed`
- `crs_status = passed`
- `missing_visual_layer_count = 0`
- `spatial_check_status = passed`

## 4. 结论

- Segment package 不暴露、不消费 `RADIUS_M`；空间范围固定为 T01 Segment geometry `200m` buffer。
- T10/T06 matched rows 被保留为 evidence reference，不再扩张 spatial slice 范围。
- 多 Segment package 的文件包和解包目录均以 `<SegmentID>/` 作为一级目录。
- 解包后的 package 可直接交给 `scripts/t10_run_e2e_cases.sh` 完成本地 T10 replay。
- Segment no-candidate handoff 的审计 reason 已同步为 `no_eligible_candidates_in_segment_geometry_buffer`。
