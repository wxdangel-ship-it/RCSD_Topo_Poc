# T12 FRCSD 质量审计验证报告

**验证日期**：2026-07-18
**分支**：`codex/003-t12-frcsd-quality-audit`
**本地结论**：通过；内网完整数据尚未执行。

## 1. 验证范围与环境

- 用例：`E:\TestData\POC_QA\T10\1026960`
- 处理环境：WSL2、Python 3.10.12、GeoPandas 1.1.x、Shapely 2.1.2。
- QGIS：3.40.14；QGIS 工程 CRS 为 `EPSG:3857`。
- 原始 1V1 FRCSD：Road 4,289、Node 4,762；SWSD Segment 1,267。
- 最终本地验证根：`outputs/_work/t12_validation_1026960_final`。
- 输入只读；所有运行和空间工程均记录 `silent_fix=false`。

## 2. 1026960 业务结果

| 检查项 | 结果 |
|---|---:|
| 自动候选 | 35 |
| 无复核模式 confirmed / manual | 0 / 35 |
| 冻结复核后 confirmed / excluded / manual | 10 / 25 / 0 |
| confirmed 类型 | `directed_carrier_missing=8`；`required_local_connectivity_missing=2` |
| 两端已锚定 Segment 审计数 | 634 |
| T07 truth anchor | 348 / 348 通过 |
| T07 anchor 到 RCSDIntersection 最大距离 | 4.801564 m（门槛 50 m） |
| FRCSD Road 端点缺失 | 0 |
| 无效/空几何 | 0 |

确认问题 ID：

1. `1001432_1019757`
2. `1019779_1026330`
3. `1039319_1049250`
4. `504597284_603597212`
5. `612408195_991266`
6. `84975803_1023802`
7. `953923_953936`
8. `991145_991164`
9. `997356_1029576`
10. `998051_501667982`

专项假阳性：`1001716_1010487` 由 50 m portal 找到正反向等价 carrier；`1039488_1039490` 由 T05/T07 grouped-node portal 找到正反向等价 carrier。生产源码中未出现这两个对象 ID。

T06 仅作为只读交叉证据；本次 manifest 以 `derived_copy_on_write` 绑定同批次 T05，并登记 summary、rejected、buffer-only probe、failure business audit、problem registry、replacement plan 六类工件及 SHA-256，共覆盖 713 个 Segment 证据键。

## 3. T10 业务效果回归

含 T12 的完整 1026960 T10 运行根：

`outputs/_work/t10_t12_acceptance/t10_t12_1026960_acceptance_v3`

- 1/1 Case 通过；11/11 stage 通过；总耗时 627.528292 s。
- stage 顺序为 `t01 -> t07 -> t03 -> t04 -> t05 -> t06_step12 -> t06_step3 -> t12 -> t11 -> t09_step12 -> t09_step3`。
- T12 stage 为 `audit_only=true`，耗时 16.459829 s，结果 35/10/25/0。
- T12 默认关闭；关闭时沿用原 `T10_V1_CHAIN` 和原 stage order，full runner manifest 也不登记 T12。

与兼容实验基线作规范化内容比较：

| 业务工件 | 要素数 | 规范化 SHA-256 | 结果 |
|---|---:|---|---|
| T06 FRCSD Road | 3,471 | `faec51c773e73e97ce7de5167051aa6550f0d431efb6a4e0d42c79a9d35f9dba` | 相同 |
| T06 FRCSD Node | 4,277 | `205da28e1d42029b9536563dba2ee00c718c9593d9dc90f2e0eafa9d27496877` | 相同 |
| T06 Segment relation | 1,267 | `c4cd49aab118725736e2f6fe4a40676222821dd2c72ea04c182996d4ef55968d` | 相同 |
| T09 restriction | 378 | `15416ce49c68faf172e5ad09e5b822327e9d09ad7357775c8f7d9f3f8c8b631d` | 相同 |
| T11 candidate CSV | - | `5424dde59c0eaeec679a3a195809c16e6b8151fe20c417c8bea3878b339c1e75` | 原始字节相同 |

GeoPackage 容器字节可能受 SQLite 元数据影响，因此本表以全部字段和规范化 geometry 的确定性内容摘要证明业务等价；T11 CSV 直接比较原始字节。

## 4. 性能与 QGIS

- 同一 WSL/Python 环境重跑兼容分析基线：11.128637 s。
- 正式 T12（含复核发布和输出）：7.356357 s，为基线的 66.103%，满足 `<=150%`。
- QGIS 工程：`outputs/_work/t12_validation_1026960_final/qgis/T12_1026960_FRCSD_QUALITY_AUDIT.qgz`。
- 工程回读通过：10 个图层全部有效、全部 `EPSG:3857`，source path 可定位。
- DriveZone 仅为 evidence-only：确认问题线的面内覆盖率为 87.0919%。通用 90%/95% 叠加阈值不通过，但非空、CRS 和叠加计算通过；该通用阈值未被固化为 T12 判错规则。

## 5. 自动化与需求核对

- 相关自动化：103 passed，2 个 PyProj/NumPy deprecation warnings。
- Shell syntax、root CLI help、T12 entry help、变更 Python compile、`git diff --check` 均通过。
- FR-001~FR-005：通过；模块、原始 target、SWSD、T05/T07/RCSDIntersection、T06 六类只读证据合同已落地。
- FR-006~FR-010：通过；局部/全图、有向/无向、长度/偏离/路径证据及复核三态完整，不发布概率等级。
- FR-011~FR-016：通过；无生产对象白名单、无 silent fix、CRS/几何/端点/指纹/环境/输出可审计。
- FR-017~FR-020：通过本地实现与合同测试；T12 为 T10 可选 audit-only stage，内网 full runner 支持预检、resume、manifest、稀疏进度和性能字段。
- FR-021~FR-022：通过；35/10/25/0 与确认 ID 精确匹配，两项复杂 portal 假阳性由通用逻辑排除。
- SC-001~SC-005：通过；已确认真值召回 10/10，发布准确率 10/10，全部候选可追溯且 `silent_fix=false`。
- SC-006：通过，正式 T12 / 同环境基线 = 66.103%。
- SC-007：通过，T06/T11/T09 业务工件内容一致，T12 关闭时默认链路不变。
- SC-008：通过自动化合同；缺输入、CRS 冲突、证据批次不一致和同名输出目录覆盖风险均在处理前阻断。

## 6. 尚未执行

未获得内网完整数据执行能力，因此没有声称完成内网全量运行。需在内网以 `RUN_T12=1`、显式 `FRCSD_1V1_ROADS_PATH` / `FRCSD_1V1_NODES_PATH` 启动 `scripts/t10_run_innernet_full_pipeline.sh`；若需要发布最终确认问题，还应提供本批次 `T12_REVIEW_DECISIONS`。
