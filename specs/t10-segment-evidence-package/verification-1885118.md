# 1885118 Segment 级证据包验证记录

**验证日期**：2026-06-30
**验证范围**：T10 Segment 级证据包打包、文本分片、解包、本地 T10 replay。
**状态**：已完成当前无半径版本的本地验证；1885118 抽样 Segment 的打包、分片、解包和本地 replay 均通过。T03/T04 在 Segment evidence dependency closure 内合法无候选时，以 `segment_no_candidate_handoff=true` 的显式空 handoff 保持完整 T10 链路，不回退到人工半径或无关全量候选。

## 1. 验证输入

- 基线指针：`outputs/baselines/LATEST_T10_4CASES_BASELINE.txt`
- T10 run root：`/mnt/e/work/rcsd_topo_poc/outputs/baselines/t10_4cases_08aa76c_20260628_155754/e2e_full/cases/1885118`
- 抽样 Segment：
  - `924076_14313744`
  - `1534342_62397379`
  - `1537607_512643052`
- package id：`t10_segments_1885118_sample_noradius_20260630`
- Segment 选择方式：`swsd_segment_e2e_evidence_dependency_closure`，不暴露也不使用人工半径参数。

本验证使用当前本地可访问的既有 T10/T06 输出与 case package external input slices；未声明或执行内网环境操作。

## 2. 打包结果

- package 目录：`outputs/_work/t10_segment_evidence_verify_1885118_noradius/packages/t10_segments_1885118_sample_noradius_20260630`
- multi manifest：`outputs/_work/t10_segment_evidence_verify_1885118_noradius/packages/t10_segments_1885118_sample_noradius_20260630/t10_multi_segment_evidence_manifest.json`
- multi summary：`outputs/_work/t10_segment_evidence_verify_1885118_noradius/packages/t10_segments_1885118_sample_noradius_20260630/t10_multi_segment_evidence_summary.json`
- summary 结论：
  - `passed = true`
  - `segment_count = 3`
  - `materialization_mode = spatial_slice`
  - `materialized_file_count = 27`
  - `matched_evidence_artifact_count = 16`
  - `failed_segment_count = 0`

每个 Segment 均生成独立 `cases/segment_<SegmentID>/` 用例目录；每个目录包含 9 个 external input slot，无缺失 slot。

| SegmentID | CaseID | materialized files | matched evidence artifacts | package status |
|---|---|---:|---:|---|
| `924076_14313744` | `segment_924076_14313744` | 9 | 5 | passed |
| `1534342_62397379` | `segment_1534342_62397379` | 9 | 6 | passed |
| `1537607_512643052` | `segment_1537607_512643052` | 9 | 5 | passed |

## 3. 文本包与解包结果

- 文本包首片：`outputs/_work/t10_segment_evidence_verify_1885118_noradius/bundles/t10_segments_1885118_sample_noradius_20260630.txt`
- 文本包第二片：`outputs/_work/t10_segment_evidence_verify_1885118_noradius/bundles/t10_segments_1885118_sample_noradius_20260630.part_0002_of_0002.txt`
- 分片大小：
  - part 1：`256000` bytes
  - part 2：`71078` bytes
- 解包目录：`outputs/_work/t10_segment_evidence_verify_1885118_noradius/decoded/t10_segments_1885118_sample_noradius_20260630`
- 解包验证文件：
  - `outputs/_work/t10_segment_evidence_verify_1885118_noradius/decoded/t10_segments_1885118_sample_noradius_20260630/t10_multi_segment_evidence_manifest.json`
  - `outputs/_work/t10_segment_evidence_verify_1885118_noradius/decoded/t10_segments_1885118_sample_noradius_20260630/t10_multi_segment_evidence_summary.json`

## 4. 本地 T10 replay 结果

- replay run root：`outputs/_work/t10_segment_evidence_verify_1885118_noop2/e2e_runs/t10_segments_1885118_sample_noop2_20260630_e2e`
- replay summary：`outputs/_work/t10_segment_evidence_verify_1885118_noop2/e2e_runs/t10_segments_1885118_sample_noop2_20260630_e2e/t10_e2e_run_summary.json`
- replay 总结：
  - `status = passed`
  - `passed = true`
  - `case_count = 3`
  - `completed_case_count = 3`
  - `passed_case_count = 3`
  - `failed_case_count = 0`
  - `blocked_case_count = 0`
  - `duration_seconds = 262.156917`
  - `t06_visual_check_case_count = 3`
  - `upstream_feedback_segment_count = 8`
  - `upstream_pair_anchor_endpoint_cluster_count = 10`
  - `upstream_side_group_candidate_count = 1`
  - `upstream_side_group_endpoint_candidate_count = 2`

| CaseID | replay status | passed stages | no-candidate handoff |
|---|---|---|---|
| `segment_1534342_62397379` | passed | `t01,t03,t04,t05,t06_step12,t06_step3,t07,t09_step12,t09_step3` | none |
| `segment_1537607_512643052` | passed | `t01,t03,t04,t05,t06_step12,t06_step3,t07,t09_step12,t09_step3` | `t03,t04` |
| `segment_924076_14313744` | passed | `t01,t03,t04,t05,t06_step12,t06_step3,t07,t09_step12,t09_step3` | `t04` |

no-candidate handoff 审计：

- `segment_1537607_512643052` 的 T03：`segment_no_candidate_handoff=true`，`noop_reason=no_eligible_candidates_in_segment_dependency_closure`，输出 `t03/t03/nodes.gpkg`、空 `virtual_intersection_polygons.gpkg`、空 `t03_swsd_rcsd_relation_evidence.csv/json` 和空 `intersection_match_t03.geojson`。
- `segment_1537607_512643052` 的 T04：`segment_no_candidate_handoff=true`，输出 `t04/t04/nodes.gpkg`、空 `divmerge_virtual_anchor_surface.gpkg`、空 `divmerge_virtual_anchor_surface_audit.gpkg`、空 `t04_swsd_rcsd_relation_evidence.csv/json` 和空 `intersection_match_t04.geojson`。
- `segment_924076_14313744` 的 T04：`segment_no_candidate_handoff=true`，输出同类空 T04 handoff。

T06 visual check：

| CaseID | status | CRS | missing visual layers | spatial check | Step2 replaceable | Step3 replacement success |
|---|---|---|---:|---|---:|---:|
| `segment_1534342_62397379` | passed | passed | 0 | passed | 4 | 4 |
| `segment_1537607_512643052` | passed | passed | 0 | passed | 0 | 0 |
| `segment_924076_14313744` | passed | passed | 0 | passed | 0 | 0 |

`1537607_512643052` 与 `924076_14313744` 的 T06 Step2/Step3 替换计数为 0，表示该 Segment 闭包在当前抽样用例中不可替换；这不是 replay 失败，也不应通过半径扩张引入无关候选。

## 5. 验证命令

当前无半径版本的打包使用：

```bash
bash scripts/t10_pack_innernet_segments.sh \
  --case-id 1885118 \
  --t10-run-root /mnt/e/work/rcsd_topo_poc/outputs/baselines/t10_4cases_08aa76c_20260628_155754/e2e_full/cases/1885118 \
  --external-input-root /mnt/e/TestData/POC_Data/T10/1885118/external_inputs \
  --segment-id 924076_14313744 \
  --segment-id 1534342_62397379 \
  --segment-id 1537607_512643052 \
  --out-root /mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t10_segment_evidence_verify_1885118_noradius \
  --package-id t10_segments_1885118_sample_noradius_20260630
```

当前通过版本的本地 replay 使用：

```bash
OUT_ROOT=/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t10_segment_evidence_verify_1885118_noop2/e2e_runs \
RUN_ID=t10_segments_1885118_sample_noop2_20260630_e2e \
CONTINUE_ON_ERROR=1 \
EXIT_ZERO=1 \
bash scripts/t10_run_e2e_cases.sh \
  --package-dir /mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t10_segment_evidence_verify_1885118_noradius/packages/t10_segments_1885118_sample_noradius_20260630
```

代码层回归验证：

```bash
bash scripts/t10_pack_innernet_segments.sh --help | tee /tmp/t10_segment_help.txt
! rg -n "RADIUS_M|radius" /tmp/t10_segment_help.txt
bash -n scripts/t10_pack_innernet_segments.sh
.venv/bin/python -m py_compile \
  src/rcsd_topo_poc/modules/t10_e2e_orchestration/case_runner.py \
  src/rcsd_topo_poc/modules/t10_e2e_orchestration/segment_noop_handoffs.py \
  src/rcsd_topo_poc/modules/t10_e2e_orchestration/spatial_slice.py \
  src/rcsd_topo_poc/modules/t10_e2e_orchestration/segment_package.py
.venv/bin/python -m pytest tests/modules/t10_e2e_orchestration -q
git diff --check
```

## 6. 结论

本轮验证确认：

- Segment 级证据包入口已不依赖 `RADIUS_M` 或人工半径参数。
- 一次输入多个 `SegmentID` 后，每个 Segment 独立形成 `cases/segment_<SegmentID>/` 轻量本地 T10 用例。
- 当前包可以导出为文本分片，并可解包恢复 multi Segment package。
- 1885118 抽样 3 个 Segment 的本地 T10 replay 全部通过，且每个 Case 均输出完整阶段状态、T06 visual check 和 upstream feedback。
- T03/T04 在 Segment 闭包内合法无候选时，以可审计空 handoff 继续链路；这保留了失败 Segment 分析所需的端到端执行形态，同时不扩大打包范围。

因此，当前 1885118 抽样验证达到 Segment 级无半径打包到本地 T10 完整 replay 的预期。
