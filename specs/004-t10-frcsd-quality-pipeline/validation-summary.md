# Validation Summary: T10 FRCSD 质量检查专用流水线

## 结论

本地裁剪用例 `1026960` 已通过专用入口的完整端到端运行。最终有效顺序为：

`T01 -> T07 Step1/2 -> T03 -> T04 -> T05 -> T06 Step1/2 -> T06 Step3 -> T11 -> T12 -> T09`

总 manifest 为 `passed`，未出现 T08 stage。T12 仍审计调用方显式提供的原始 1V1 FRCSD；T09 的 Road、Node、Segment relation 均明确指向 T06 Step3 输出，未消费 T12。

## 真实运行证据

- run root：`outputs/_work/t10_frcsd_quality_pipeline_acceptance/t10_frcsd_quality_1026960_acceptance_v7`
- 总 manifest：`t10_innernet_full_pipeline_manifest.json`
- 总 summary：`t10_innernet_full_pipeline_summary.json`
- 总耗时：`681.018s`
- T12：候选 `35`、确认质量问题 `10`、人工排除 `25`、待人工复核 `0`
- T12 的 35 个候选 ID、10 个确认 ID、25 个排除 ID 均与既有 Case 验收逐项一致
- T12 问题类型：`directed_carrier_missing=8`、`required_local_connectivity_missing=2`
- T11：候选 `291`；分类统计与既有 Case 运行一致
- T09：restriction `378`；与既有 Case 运行一致
- T06 Step2：replaceable `607`、rejected `106`；T06 Step3：FRCSD Road `3470`、Node `4276`、final topology fail `0`，与既有 Case 运行一致

## 裁剪边界与兼容承载

1. 原始 1V1 FRCSD 直接作为 T04 的 RCSD 输入时，T04 按合同阻断：缺少 `snodeid/enodeid/snodeid_value/enodeid_value`。因此正式验收没有伪造字段或 silent fix；T03~T06 使用已显式生成的兼容承载切片，T12 target 始终使用原始 1V1 FRCSD。
2. 首次 full-profile 验收未传 Case manifest 时得到 `54/10/25/19`。对比确认新增 19 项全部位于裁剪边界；补充显式 `T12_CASE_MANIFEST` 后得到 `crop_edge_excluded_count=19`，恢复为 `35/10/25/0`。全图运行没有裁剪边界，因此该参数必须留空。
3. `RCSDIntersection` 作为 T07 标准路口真值输入；T12 真值审计识别 T07 anchor `348` 个，最大匹配距离 `4.802m`，无缺失或未匹配 anchor，状态为 `pass`。

## GIS 与质量门禁

- CRS：全部输入和处理 CRS 为 `EPSG:3857`，`transform_applied=false`；没有隐式坐标变换。
- 拓扑：原始 FRCSD Road `4289`、Node `4762`，端点缺失 `0`；T06 最终 FRCSD topology fail `0`。T06 surface topology 的既有 12 条失败审计仍保留在 T06 工件中，T12 未静默修复或吞掉该证据。
- 几何语义：Segments、SWSD Road/Node、原始 FRCSD Road/Node、RCSDIntersection、DriveZone 的 invalid geometry 均为 `0`；检查语义为 SWSD 要求方向与原始 FRCSD 全图/局部 carrier 通行路径对比。
- 审计追溯：总 manifest 记录 inputs、stage order、每阶段输入输出和日志；T12 manifest 记录原始 target 哈希、参数、CRS、运行环境、人工复核来源及 `silent_fix=false`。
- 性能：T12 对 `1267` 个 Segment、`4289` 条 FRCSD Road、`4762` 个 FRCSD Node 的耗时为 `7.571s`；完整裁剪用例流水线耗时为 `681.018s`。

## 自动化验证

- `tests/modules/t10_e2e_orchestration` + `tests/modules/t12_frcsd_quality_audit`：`96 passed`，仅 2 条第三方 pyproj/NumPy deprecation warning。
- `tests/modules/t06_segment_fusion_precheck`：`487 passed`。
- 两个 T10 shell 入口 `bash -n` 通过；专用入口 help、缺失 FRCSD target、冲突 `RUN_T08/RUN_T12` 和可选 Case manifest 转发测试通过。
- 最终联合体量扫描：31 个新增/修改源码、脚本和测试，`>=100KB` 为 0。

## 执行边界

以上是本机 WSL 对本地裁剪数据的实跑结论。没有获得内网完整数据执行能力，因此不声称内网全图已经运行；内网正式运行仍需使用相同入口并保留 run root、manifest、summary 和日志后再验收。
