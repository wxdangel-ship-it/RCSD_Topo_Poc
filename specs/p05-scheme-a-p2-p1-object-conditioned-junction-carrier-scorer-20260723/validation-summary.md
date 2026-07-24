# P05-Scheme-A-P2-P1 验证总结

## 1. 正式结论

本阶段已完成，正式判定为 **`P05_SCHEME_A_P2_P1_SAFETY_NO_GO`**。

该结论不表示神经网络不能学习 carrier。Road endpoint/JunctionUnit 条件化后，独立 Node top-1 的 `0.7558` 提升为联合 Node exact `0.9965~0.9985`，并且三个 seed 均保持 49 `LEGAL` + 2 `EXPECTED_FAIL`。失败集中在“哪些预测可以无人复核地自动接受”：每个 seed 仍有 `9~17` 个错误接受，总体和 `USE_RCSD` safe accepted coverage 不能同时达到 `0.50`，异常 precision 也只有 `0.2851~0.3936`。

因此当前 scorer 可作为排序、review 和异常线索研究证据，但不得自动替换 SWSD、不得接在线 proposal 或生产主链。

## 2. 正式证据

- dataset：`p05_scheme_a_p2_p1_dataset_20260723_01`
- OOF Run A：`p05_scheme_a_p2_p1_oof_20260723_01`
- OOF Run B：`p05_scheme_a_p2_p1_oof_20260723_02`
- audit：`p05_scheme_a_p2_p1_audit_20260723_02`
- `p05_scheme_a_p2_p1_audit_20260723_01` 是 Windows 峰值内存 API 句柄声明错误造成的不完整开发审计，不作为正式证据，也未删除原始文件。

## 3. Gate 结果

### Gate 0/1：数据、可达性与泄漏

- 51 Case、8,863 Segment、28,240 Node group、Movement=0。
- Segment candidate `23,758`、Node candidate `79,334`、truth-free compatibility edge `77,964`。
- Segment 和条件化 Node truth reachability 均为 `1.0`；51/51 compatibility Oracle exact。
- truth/Oracle/绝对坐标 feature hit=0，candidate-first=true，骨架 mutation=0。
- 共享 Node payload 冲突触发 57 个 Segment 的 Junction fallback；未通过修图或 silent fix 消除冲突。

### Gate 2：对象评分

| seed | Segment macro-F1 | USE_RCSD recall | Junction Node exact | Node exact | ECE |
|---:|---:|---:|---:|---:|---:|
| 17 | 0.999114 | 1.000000 | 0.996261 | 0.996530 | 0.000721 |
| 29 | 0.999164 | 1.000000 | 0.996573 | 0.997309 | 0.001644 |
| 43 | 0.819001 | 1.000000 | 0.998131 | 0.998513 | 0.001877 |

seed 43 的 Segment macro-F1 失败来自 40 个 `REVIEW_FALLBACK` 中仅 12 个保持 Review，28 个被预测为 `KEEP_SWSD`；不得从分母隐藏。

### Gate 3：安全自动接受

| seed | 错误接受 | accepted precision | 总体 coverage | USE_RCSD coverage | fallback recall | anomaly precision |
|---:|---:|---:|---:|---:|---:|---:|
| 17 | 17 | 0.998523 | 0.310218 | 0.099908 | 0.994640 | 0.346040 |
| 29 | 9 | 0.999307 | 0.350241 | 0.002750 | 1.000000 | 0.285055 |
| 43 | 17 | 0.999110 | 0.514999 | 0.265811 | 0.981688 | 0.393570 |

Gate 3 三个 seed 均失败。模型对 `USE_RCSD` 真值的排序 recall 为 1.0，但当前 fold-local confidence/anomaly calibration 不能同时保证零错误和 50% 自动接受覆盖率。

### Gate 4：RoadGraph 安全

- 每个 seed 49 `LEGAL` + 2 精确 `EXPECTED_FAIL`，新增失败=0。
- 153 张图全部为 `EPSG:3857`；合法图 CRS、geometry、Road/Node 引用和有向拓扑 hard failure=0。
- 6 个 expected failure 只保留已登记 endpoint 缺失，共 12 条 endpoint/edge 失败；没有额外 CRS/geometry 错误。
- `content_repair=false`、`relaxation=false`、`silent_fix=false`、`skeleton_mutation_count=0`。

P2-P1 不发布新的 GPKG/GeoJSON 图层，因此 QGIS polygon overlay 不适用；QGIS 3.40.14 runtime 已确认存在，正式 GIS 证据来自物化器读取冻结源 GPKG payload 后执行的 CRS、geometry、引用和拓扑 hard gate。

### Gate 5：确定性与资源

- Run A/B 的 15 个 model state、checkpoint、词表、阈值、training history、score、selection、effective selection 和规范化 RoadGraph 内容全部一致。
- 参数量 `3,551,314~3,551,634`，CPU-only。
- 3 seeds 训练 wall `471.231s`，低于 6h。
- 单 Case scoring P95=`0.300s`、max=`0.968s`，低于 `5s/20s`。
- benchmark 进程 peak working set=`1,063,227,392` bytes，低于 16GB。

## 4. 技术解释与下一轮边界

本阶段已经排除两类旧问题：正确 carrier 不在候选集合，以及把完整 T06/PTO Node Oracle错误地直连到混合 Road 真值。现有失败属于新的、范围更窄的问题：

1. 少量 held-out Segment 错误仍有很高置信度，并会通过合法 endpoint 关系连带形成多个 Node 错误；通用图约束只能保证“图合法”，不能判断业务 carrier 是否选对。
2. 当前 anomaly head 对 `KEEP_SWSD` 中的现实冲突区分能力不足；为了提高 fallback recall 会显著牺牲 precision 和 coverage。
3. `REVIEW_FALLBACK` 在 seed 43 不稳定，表明当前共享编码器/单一 early-stop 指标对少数安全类别保护不足。

后续若另行授权，应新建独立阶段研究 class-aware safety calibration、cross-fitted abstention、Review/anomaly 专门 head 或分层 scorer；不得根据本次 held-out 结果直接调阈值后重用同一正式分母宣称 GO，也不应继续单纯增加当前模型 epoch。

