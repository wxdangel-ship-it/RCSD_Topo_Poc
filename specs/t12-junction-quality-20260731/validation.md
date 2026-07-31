# T12 Junction 质量输出验证记录

## 1. 实施结论

- T12 schema 升级为 `2026-07-31.t12_frcsd_quality_audit.v9`。
- 既有 Segment LineString 审计保持原算法、文件名、状态和 review contract。
- 新增 T03/T07 Junction Point 审计及独立 candidates/confirmed/exclusions/evidence。
- T07 只修正两处架构文字：Step1 `has_evd` 只使用 DriveZone；未修改
  T07 代码、接口和算法。
- T03、T05、T06、T09、T11 算法和接口未修改。
- T10 只增加 T03/T07 到 T12 的显式 handoff 与 Junction 输出登记。

## 2. 接口与兼容

正式 Python 入口新增两个可选参数：

```text
--t03-run-root
--t07-step3-run-root
```

既有必选参数、默认值和调用方式不变。旧调用不提供 Junction 来源时：

- 正常生成结构完整的空 Junction 文件；
- Segment 结果不变；
- `junction_input=0.0000059s`、
  `junction_audit=0.0000068s`，走空源 fast path。

正式新增输出：

```text
t12_frcsd_junction_quality_candidates.csv/.gpkg
t12_frcsd_confirmed_junction_quality_issues.csv/.gpkg
t12_frcsd_junction_quality_exclusions.csv
t12_frcsd_junction_carrier_evidence.gpkg
```

Junction 主几何为 Point；support Road、FRCSD endpoint、target projection
和 T07 conflict link 只进入 evidence。Segment 主几何继续为 LineString。

## 3. T03 真实 Case

数据：

- `E:\TestData\POC_Data\T03`
- `E:\TestData\POC_Data\T03_Error`
- 正式 T03/T03_Error `final_replay_v3` rejected 审计链

确认结果精确为：

| JunctionID | detection rule | issue type |
|---|---|---|
| `522008569` | `shared_degree1_terminal_collapse` | `junction_required_topology_missing` |
| `522806716` | `shared_degree1_terminal_collapse` | `junction_required_topology_missing` |
| `520394575` | `multi_component_unmatched_support` | `junction_reality_or_precision_gap` |
| `622700016` | `multi_component_unmatched_support` | `junction_reality_or_precision_gap` |

指定 16 个负样本均未进入 confirmed。`523923800` 为 T03 Step7 accepted，
不属于 rejected candidate；其余负样本按 eligibility、无效几何、
constraint split、非 terminal、support 不足或其它强门禁排除。

真实 Case 测试连续运行两次均为 `1 passed`，确认集合完全一致。合并 QGIS
审计结果去重后为 `candidate/confirmed/excluded = 16/4/12`。

## 4. T07 稳定失败

单元与工作流测试验证：

- `one_target_to_many_base`：每个 target 一个 Junction Point；
- `many_target_to_one_base`：每个 target 一个 Point，共享 deterministic
  `conflict_group_id`；
- `duplicate_target_rows`：不生成 candidate，只进入 ignored 计数；
- T12 不重新裁决 T07。

本地没有提供新的全量 T07 Step3 实际运行根，因此本轮不把合成单测解释为
内网全量数量结论。

## 5. Segment 冻结回归与性能

`1026960` v9 旧调用回归：

| candidate | confirmed | excluded | manual |
|---:|---:|---:|---:|
| 63 | 10 | 53 | 0 |

10 个 confirmed candidate ID/type 与 v8 冻结基线完全一致：

```text
1001432_1019757
1019779_1026330
1039319_1049250
504597284_603597212
612408195_991266
84975803_1023802
953923_953936
991145_991164
997356_1029576
998051_501667982
```

当前 Windows/Python 运行：

- T12 内部总耗时：`7.4194369s`；
- candidate stage：`6.7428439s`；
- 空 Junction 两阶段合计小于 `0.000014s`；
- 外部墙钟：`8.1373s`。

历史 v8 验证记录为 WSL 双跑均值 `11.209s`、candidate stage
`6.748s`。运行环境不同，因此不能把总耗时差直接解释为性能提升；但当前
candidate stage 持平，空 Junction source 无可观测退化。完整内网启用 T03/T07
后的全量耗时仍须由内网脚本复验。

## 6. QGIS 与 GIS 五项

QGIS 版本：`3.40.14-Bratislava`。

工程：

```text
outputs/_work/t12_junction_quality_20260731/real_case_audit_20260731_b/
  t12_junction_real_case_audit.qgz
```

工程包含：

- T12 candidates、confirmed、exclusions；
- support Road、target projection、FRCSD endpoint；
- 原始 SWSD Road/Node/DriveZone；
- 原始 RCSD/FRCSD Road/Node。

机器检查：

- CRS：全部 `EPSG:3857`，PASS；
- 图层有效性：全部有效，PASS；
- 原始 SWSD 与原始 RCSD/FRCSD：均存在，PASS；
- confirmed/excluded：`4/12`，PASS；
- confirmed Point 对 DriveZone 覆盖率：`4/4 = 1.0`，阈值
  `layer>=0.90 / overall>=0.95`，PASS；
- topology：不补点、不 snap、不 repair，`silent_fix=false`；
- 几何语义：Point 主问题与 Road/endpoint/projection 根因分层；
- 审计追溯：来源绝对路径、工件指纹、CRS、规则、参数、决定和环境可定位。

机器报告：

```text
t12_junction_qgis_project_check.json
t12_junction_drivezone_overlay_gate.json
t12_junction_real_case_validation_summary.json
```

## 7. 自动测试与治理

- T12 全量：`69 passed, 2 warnings`；warning 为既有
  pyproj/NumPy deprecation。
- T10/T12 工作流：`7 passed`。
- 真实 Case 双跑：两次均 `1 passed`。
- `compileall`：PASS。
- `bash -n`：
  - `scripts/t10_run_innernet_full_pipeline.sh` PASS；
  - `scripts/t12_rerun_frcsd_junction_quality_innernet.sh` PASS。
- `git diff --check`：PASS。
- 17 个新增/修改源码、脚本、测试和 QGIS validation 文件均低于
  `100000 bytes`；最大为既有 full runner `67248 bytes`。

## 8. 内网 T12-only 入口

正式入口：

```text
scripts/t12_rerun_frcsd_junction_quality_innernet.sh
```

脚本使用环境变量接收正式上游路径，拒绝覆盖已有 run root，显示当前 stage，
结束时打印 Segment/Junction 计数、耗时和 summary 路径，并验证所有必要
Segment/Junction 文件存在。

本轮未执行内网数据，也未 commit、push 或 merge。
