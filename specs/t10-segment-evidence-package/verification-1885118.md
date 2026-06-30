# 1885118 Segment 级证据包验证记录

**验证日期**：2026-06-30
**验证范围**：T10 Segment 级证据包打包、文本分片、解包、本地 T10 replay。
**状态**：已完成本地验证；replay 结果包含 2 个通过 Segment 和 1 个可定位到 T04 的失败 Segment。

## 1. 验证输入

- 基线指针：`outputs/baselines/LATEST_T10_4CASES_BASELINE.txt`
- T10 run root：`/mnt/e/work/rcsd_topo_poc/outputs/baselines/t10_4cases_08aa76c_20260628_155754/e2e_full/cases/1885118`
- 抽样 Segment：
  - `924076_14313744`
  - `1534342_62397379`
  - `1537607_512643052`
- package id：`t10_segments_1885118_sample_20260630`
- Segment 选择方式：`swsd_segment_e2e_evidence_dependency_closure`，不使用人工半径参数。

本验证使用当前本地可访问的既有 T10/T06 输出与 case package external input slices；未声明或执行内网环境操作。

## 2. 打包结果

- package 目录：`outputs/_work/t10_segment_evidence_verify_1885118/packages/t10_segments_1885118_sample_20260630`
- multi manifest：`outputs/_work/t10_segment_evidence_verify_1885118/packages/t10_segments_1885118_sample_20260630/t10_multi_segment_evidence_manifest.json`
- multi summary：`outputs/_work/t10_segment_evidence_verify_1885118/packages/t10_segments_1885118_sample_20260630/t10_multi_segment_evidence_summary.json`
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

- 文本包首片：`outputs/_work/t10_segment_evidence_verify_1885118/bundles/t10_segments_1885118_sample_20260630.txt`
- 文本包第二片：`outputs/_work/t10_segment_evidence_verify_1885118/bundles/t10_segments_1885118_sample_20260630.part_0002_of_0002.txt`
- 分片大小：
  - part 1：`256000` bytes
  - part 2：`75074` bytes
- 解包目录：`outputs/_work/t10_segment_evidence_verify_1885118/decoded/t10_segments_1885118_sample_20260630`
- 解包验证文件：
  - `outputs/_work/t10_segment_evidence_verify_1885118/decoded/t10_segments_1885118_sample_20260630/t10_multi_segment_evidence_manifest.json`
  - `outputs/_work/t10_segment_evidence_verify_1885118/decoded/t10_segments_1885118_sample_20260630/t10_multi_segment_evidence_summary.json`

## 4. 本地 T10 replay 结果

- replay run root：`outputs/_work/t10_segment_evidence_verify_1885118/e2e_runs/t10_segments_1885118_sample_20260630_e2e`
- replay summary：`outputs/_work/t10_segment_evidence_verify_1885118/e2e_runs/t10_segments_1885118_sample_20260630_e2e/t10_e2e_run_summary.json`
- replay 总结：
  - `status = failed`
  - `case_count = 3`
  - `completed_case_count = 3`
  - `passed_case_count = 2`
  - `failed_case_count = 1`
  - `blocked_case_count = 0`
  - `duration_seconds = 227.561824`
  - `t06_visual_check_case_count = 3`
  - `upstream_feedback_segment_count = 5`
  - `upstream_side_group_candidate_count = 1`
  - `upstream_side_group_endpoint_candidate_count = 2`
  - `upstream_pair_anchor_endpoint_cluster_count = 4`

| CaseID | replay status | passed stages | failed / blocked stages |
|---|---|---|---|
| `segment_924076_14313744` | passed | `t01,t03,t04,t05,t06_step12,t06_step3,t07,t09_step12,t09_step3` | none |
| `segment_1534342_62397379` | passed | `t01,t03,t04,t05,t06_step12,t06_step3,t07,t09_step12,t09_step3` | none |
| `segment_1537607_512643052` | failed | `t01,t03,t07` | `t04=failed`; `t05,t06_step12,t06_step3,t09_step12,t09_step3=blocked` |

失败 case 的 T04 stdout 记录：

```text
Candidate discovery: representative node, has_evd=yes, is_anchor=no, kind_2 in {8,16,128}.
ValueError: No eligible T04 candidates were discovered.
```

该失败是本地 T10 replay 对当前 Segment package 的真实诊断结果，不是打包失败；它证明 Segment 包能够把有证据但未替换成功的 Segment 转换为可本地执行并定位阶段原因的 T10 用例。

## 5. 验证命令

```bash
.venv/bin/python -m pytest tests/modules/t10_e2e_orchestration -q
bash -n scripts/t10_pack_innernet_segments.sh
.venv/bin/python -m rcsd_topo_poc --help
git diff --check
```

补充验证：

```bash
.venv/bin/python -m pytest tests/modules/t06_segment_fusion_precheck/test_single_graph_connectivity_retry.py -q
```

## 6. 结论

本轮 Segment 级证据包能力达到以下预期：

- 支持一次输入多个 `SegmentID`。
- 每个 Segment 独立形成 `cases/segment_<SegmentID>/` 轻量本地 T10 用例。
- 打包基于既有 T10 run root、T01 Segment 和 T06 evidence 反查，不只依赖人工空间裁剪。
- 文件包可导出为自动分片文本包，并可解包恢复 multi Segment package。
- 解包或原 package 可被 `scripts/t10_run_e2e_cases.sh` 执行，本地 replay 产出阶段状态、T06 funnel、visual check 和 upstream feedback。
- 对 1885118 抽样 Segment，replay 结果能区分全链路通过与 T04 候选发现失败，满足快速定位内网 Bug 的目标。
