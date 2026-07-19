# Validation Summary：T12 自动高置信质量确认

## 1. 环境与输入

- 仓库：`E:\Work\RCSD_Topo_Poc`
- Python：WSL `.venv/bin/python` 3.10.12
- 数据：`E:\TestData\POC_QA\T10\1026960`
- 处理 CRS：`EPSG:3857`
- 最终自动验收 run：`outputs/_work/t12_auto_high_confidence_final_20260719/standalone/t12_1026960_no_review`
- 最终验收报告：`outputs/_work/t12_auto_high_confidence_final_20260719/validation-report.json`
- 带可选 review override 的验证报告：`outputs/_work/t12_auto_high_confidence_validation_script_20260719/validation-report.json`

## 2. 业务结果

无 `--review-decisions`：

- candidate：35
- confirmed：10
- excluded：25
- manual：0
- `directed_carrier_missing`：8
- `required_local_connectivity_missing`：2
- confirmed ID 与 issue type 均与冻结真值完全一致。
- 35 条决定来源全部为 `automatic_high_confidence`。

显式 review override：仍为 35/10/25/0，35 条决定来源变为 `external_review_override`，证明兼容合同有效。

## 3. 通用规则证据

- `equivalent_raw_carrier`：20
- `insufficient_anchor_confidence`：5
- `raw_carrier_missing_trusted_anchor`：10
- confirmed 锚点信用：9 条 `t07_standard_surface`，1 条 `t03_pair`。
- T07 anchor：348；唯一标准面关联 345；2 个 missing、1 个 ambiguous 均显式审计，不能获得自动确认信用。
- T12 生产包未包含 Case ID、10 个 confirmed ID 或已知 false-positive ID。

## 4. GIS 与拓扑

- 输入无效几何：全部 0。
- FRCSD Road endpoint 缺失：0。
- candidates GPKG：35 个有效 `MultiLineString`，CRS `EPSG:3857`。
- confirmed GPKG：10 个有效 `MultiLineString`，CRS `EPSG:3857`；ID 与 CSV 完全一致。
- carrier evidence：35 个 candidate Segment、501 个 portal Point、71 个 SWSD carrier LineString、212 个 FRCSD path LineString；无 invalid/empty geometry。
- `silent_fix=false`，未修改任何输入。

## 5. 性能

- 对象规模：1267 Segment、4289 FRCSD Road、4762 FRCSD Node。
- loading/preflight：2.155s
- candidate audit：3.968s
- automatic decision：0.006s
- output：1.589s
- 总耗时：7.718s

相对原同环境 5.385s 候选/人工门禁基线为约 143%，低于既有 150% 性能门槛。raw local graph 只对通过 canonical 宽筛选的候选构建。

## 6. 自动化回归

```text
104 passed, 2 warnings in 14.82s
```

范围：`tests/modules/t12_frcsd_quality_audit` 与 `tests/modules/t10_e2e_orchestration`。两条 warning 为既有 pyproj/NumPy deprecation，不影响本次结果。

## 7. 尚未验证

- 内网完整数据尚未在本会话执行；需由用户在内网环境运行正式 T10 FRCSD quality profile。
- 其它城市/完整数据的召回与参数适配仍需独立 QA；本次未把 `1026960` 的对象或真值固化进生产规则。
