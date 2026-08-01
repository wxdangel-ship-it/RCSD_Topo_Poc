# 验证记录

## 1. 结论

本地可执行范围内，T12 v10 已满足本任务的来源、分类、兼容、真实 Case、
QGIS 和 Segment 性能门禁。T07 代码、接口和算法未修改；T12 对 T07 的正式
来源只接受 Step2 final `is_anchor=fail1/fail2`，Step3 cardinality 导入数恒为 0。

内网全量尚需复核两项规模性指标：全量 Step2 的 J03/J04 集合等值，以及
Junction-enabled T12 的同机三次中位数。它们不影响本地代码和契约通过，但
不得用本地裁剪 Case 代替全量结论。

## 2. 自动测试与静态验证

- `pytest tests/modules/t12_frcsd_quality_audit tests/modules/t10_e2e_orchestration`：
  `160 passed`，2 条来自 `pyproj` 的上游弃用告警；其中包含 T12-only
  新批次失败后保留失败目录并恢复原标准批次的真实脚本级模拟。
- `compileall`：T12、T10 编排、T12 入口及两个 SpecKit 验证脚本通过。
- `bash -n`：`scripts/t10_run_innernet_full_pipeline.sh` 与
  `scripts/t12_rerun_frcsd_junction_quality_innernet.sh` 通过。
- T07 目录 `git diff -- modules/t07_semantic_junction_anchor` 为空。
- 测试覆盖 Step2 fail1/fail2、fail2 优先、证据/summary 不一致阻断、
  Step3 cardinality 零导入、七类字段、候选 ID 唯一和旧状态兼容。
- `764857`、`26981804` 在 candidates/confirmed/exclusions 中均为 0。

## 3. 真实数据回归

### 3.1 Segment 1026960

最终重放根：
`outputs/_work/t12_quality_taxonomy_step2_source_20260801/release/t12_1026960_acceptance`

- candidate/confirmed/excluded/manual：`63/10/53/0`。
- confirmed：S01=`8`、S02=`2`、S03=`0`。
- 10 个 confirmed `candidate_id` 与冻结审核表完全一致。
- 两次同输入重放的 candidates/confirmed/exclusions CSV SHA-256 分别一致：
  `03525c36...a994`、`ebc91242...7043`、`28b74d54...b48c`。

### 3.2 T03 Junction

真实 T03/T03_Error 注册集结果：candidate=`16`、confirmed=`4`、
excluded=`12`；4 个正例全部命中，16 个负例无 confirmed。

- J01：`522008569`、`522806716`。
- J02：`520394575`、`622700016`。
- TP=`4`、FP=`0`、FN=`0`。

## 4. QGIS 与 GIS 五项检查

自包含工程：
`outputs/_work/t12_quality_taxonomy_step2_source_20260801/real_qgis_audit_v10_release/t12_v10_segment_junction_audit.qgz`

- CRS：QGIS 3.40.14 校验全部图层为 `EPSG:3857`，无失效图层。
- 拓扑：只读审计，`silent_fix=false`；候选/confirmed/excluded 计数守恒且
  candidate ID 唯一。
- 几何：Segment 为线几何族（实际 WKB 为 `MultiLineString`），Junction
  为 Point；原始 SWSD、RCSD/FRCSD 与根因 evidence 均在工程中。
- 追溯：工程全部数据源位于工程目录内，外部数据源计数为 0；bundle summary、
  QGIS check 和 overlay gate JSON 均保留输入指纹、环境和计数。
- 空间覆盖：Junction confirmed 对原始 DriveZone 为 `4/4`、ratio=`1.0`；
  Segment confirmed 对原始 SWSD Segment 1m 审计缓冲为 ratio=`1.0`。
  Segment 的完整线几何不要求全部位于路口 DriveZone，因此 DriveZone 只作视觉
  上下文，不降低阈值或替换业务参考。

## 5. 性能

同一主机、同一 `1026960` 输入、`/usr/bin/time -v` 对比：

| 指标 | v9 | v10 | 比值 |
|---|---:|---:|---:|
| T12 内部 elapsed | 12.129s | 12.505s | 1.031 |
| candidate audit | 6.309s | 6.891s | 1.092 |
| 最大 RSS | 196372 KB | 198100 KB | 1.009 |

满足 Segment-only 时间不超过 110%、峰值内存不超过 120% 的门禁。
外部 wall clock 为 v9 `19.56s`、v10 `17.86s`，仅作环境观察，不替代模块内部
阶段耗时。全量 Junction-enabled 三次中位数仍由内网脚本生成后判定。

## 6. 内网待验证

1. 全量 T07 Step2 final `fail1/fail2` 与 T12 J03/J04 输出集合精确相等，
   漏报、多报、重复均为 0；Step3 import count 必须为 0。
2. Junction-enabled T12 同机三次中位数不超过 v9 的 150%，峰值内存不超过
   120%。
3. T09/T12 续跑成功后，原 T12 标准目录进入 `history/t12_frcsd_quality_audit`，
   新成果仍落在 T10 标准目录 `t12_frcsd_quality_audit/<run_id>`；续跑失败时
   失败批次进入 history，原标准批次恢复。

## 7. Git 集成

- 功能分支：`codex/t12-v10-quality-taxonomy@76b0f48`，已推送。
- 主干合并提交：`a8f7dcb`，已推送到远端 `main`。
- 合并后的 T12/T10 测试仍为 `160 passed`，T07 diff 为 0。
