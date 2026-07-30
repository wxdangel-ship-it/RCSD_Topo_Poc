# 验证记录

## 1. 测试

- T12 模块：`48 passed`，仅有 2 条既有 `pyproj`/NumPy deprecation warning。
- T10/T12 编排契约：`10 passed, 1 deselected`。
- 被 deselect 的测试只是在 Windows 进程中把 `E:\...` 路径直接交给 `bash` 时无法解析；同一入口通过 WSL 路径运行 `--help` 成功，阶段链仍为 `T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T11 -> T12 -> T09`。
- `compileall`：通过。

## 2. 真实 1026960 双跑

最终运行根：

```text
E:\Work\RCSD_Topo_Poc_t12_unexpected_reverse_20260730\outputs\_work\t12_unexpected_reverse_precision_20260730_v4
```

运行 ID：

- `t12_unexpected_reverse_run1`
- `t12_unexpected_reverse_run2`

输入为同一份冻结 1026960 Segment、prepared SWSD Road/Node、原始 1V1 RCSD/F-RCSD Road/Node、T05 anchor audit、RCSDIntersection、DriveZone 和 Case manifest。历史 T06 summary 内登记的是 WSL 路径，本次 Windows replay 使用显式 `allow_unverified_t06_evidence=true`；T06 只作交叉证据，不参与新 verdict。

### 2.1 结果

| 指标 | 数量 |
|---|---:|
| 原有 `missing_required_carrier` candidate | 35 |
| 新增 `unexpected_reverse_carrier` candidate | 28 |
| 总 candidate | 63 |
| confirmed | 11 |
| excluded | 52 |
| manual | 0 |
| 新增正式 `unexpected_reverse_carrier` | 1 |
| 新增弱锚点排除 | 22 |
| 新增 SWSD 等价反向排除 | 5 |

原有正式结果保持 `directed_carrier_missing=8`、`required_local_connectivity_missing=2`，未发生回归。

### 2.2 冻结样例

| Segment | 结果 | 证据 |
|---|---|---|
| `26219553_1026960` | confirmed `unexpected_reverse_carrier` | F-RCSD raw 反向 Road `5846061599162544/2545/2546/5846058646767192`；SWSD 全图只有不等价长绕行；双 T07 唯一标准面 |
| `624023705_39546468` | excluded | F-RCSD raw 反向 Road `5846146794258680` 可复现；SWSD 反向路径不等价；T03/T03 不满足自动确认门禁 |
| `1013614_1019738` | excluded | SWSD 存在等价反向替代路径，规则 `unexpected_reverse_swsd_equivalent` |
| `61704236_1049438` | candidate 前排除 | 位于当前 Case manifest 的 crop-edge，保持既有边界策略 |

### 2.3 确定性

双跑以下文件 SHA-256 完全一致：

- candidates：`31a2e9d4267b12ab8027ebc6c893d8fe2db2755a5cee5affcbf035befbaa520d`
- confirmed：`3f25984620910c7df5e8ec9dcd1d3fefe92b46fffdbbfba26bb5454357ea1cf9`
- exclusions：`7323a6a652c508ef5f662e1a49c0a3f4a8fb02eb7bf9588cab120f93d5d5da66`

## 3. GIS 五项

- CRS：全部输入和输出为 `EPSG:3857`，无隐式转换。
- 拓扑：F-RCSD `endpoint_missing_count=0`，`silent_fix=false`。
- 几何语义：反向路径必须是 raw direction graph 中含实际 Road 的连续路径；T07 canonical endpoint 扩展只选择 `portal_radius_m` 内正确 Voronoi 侧端点，不新增边。
- 审计追溯：manifest 保留输入绝对路径、SHA-256、参数、环境、候选政策、输出和耗时；证据 GPKG 含 `candidate_segments / anchor_portals / swsd_required_carriers / swsd_reverse_carriers / frcsd_carrier_paths` 五层。
- 性能：同一 Windows 环境旧逻辑总耗时 `4.115s`、candidate audit `3.666s`；新逻辑总耗时 `8.501s`、candidate audit `7.893s`。新增全图反向排除使本地 Case 增加约 `4.39s`，结果可验证，完整数据仍需内网实测。

## 4. QGIS 自动复核

QGIS `3.40.14` / PyQGIS 可用。对 `26219553_1026960` confirmed Segment 与原始 DriveZone 做自动 overlay gate：

- layer CRS：`EPSG:3857`
- feature：`1`
- in-road ratio：`1.0`
- gate：`PASS`
- 阈值：per-layer `0.90`，overall `0.95`

报告：

```text
E:\Work\RCSD_Topo_Poc_t12_unexpected_reverse_20260730\outputs\_work\t12_unexpected_reverse_precision_20260730_v4\qa\qgis_overlay_gate_26219553_1026960.json
```
