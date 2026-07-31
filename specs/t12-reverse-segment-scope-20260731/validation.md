# 验证记录

## 1. 自动测试

- T12 专项：`29 passed in 9.29s`。
- T12 全量终检：`59 passed, 2 warnings in 11.89s`；warning 为既有
  pyproj/NumPy deprecation，不影响本轮判定。
- T10/T12 编排兼容终检：`11 passed in 2.71s`。
- `compileall`、`git diff --check` 和最终范围检查见交付前终检。

## 2. 本地真实数据

冻结输入 `1026960` 使用 v8 双跑：

| run id | candidate | confirmed | excluded | manual |
|---|---:|---:|---:|---:|
| `t12_reverse_scope_v8_run1` | 63 | 10 | 53 | 0 |
| `t12_reverse_scope_v8_run2` | 63 | 10 | 53 | 0 |

两次 candidates、confirmed、exclusions CSV 的 SHA256 分别完全一致。
正式确认仍为 `directed_carrier_missing=8`、
`required_local_connectivity_missing=2`，没有新增或丢失原两类问题。

已知 v7 误报 `26219553_1026960` 在 v8 中：

- `decision_rule=unexpected_reverse_other_segment_covered`；
- 反向路径 4 条 raw RCSD Road 均归属
  `1026960_612408195`；
- 当前端点 Road 到对应 T07 标准面距离 `3.333536m`，超过 `1m`
  拓扑容差；
- 因而不再作为 `unexpected_reverse_carrier` 正式问题发布。

## 3. GIS 五项

- **CRS**：全部输入 `EPSG:3857`，无坐标变换，距离单位为 metre。
- **拓扑一致性**：只读判定，`silent_fix=false`；首尾 Road 必须在 `1m`
  内接触对应 T07 标准面。
- **几何语义**：剔除标准面及 `1m` 容差内共享几何后，逐 raw RCSD Road
  按 `20m coverage / 50m coverage / distance` 排序判定唯一 Segment。
- **审计追溯**：manifest 记录输入哈希、规则和环境；CSV 保留汇总根因；
  `unexpected_reverse_rcsd_ownership` GPKG 层保留 `47` 条逐 Road 空间证据。
- **QGIS 回读**：v8 工程在 QGIS `3.40.14` 回读通过，共 `31` 个有效图层；
  保留默认关闭的原始 RCSD/SWSD 两组，并为两个历史审计 Case 增加
  `4 + 1` 条逐 Road 归属层；工程数据源为相对路径。
- **性能**：同一 WSL/Python/输入各双跑，v7 总耗时均值 `10.452s`，
  v8 为 `11.209s`，增加 `7.2%`；候选阶段由 `6.616s` 增至 `6.748s`
  （`+2.0%`）。本地规模为 `1267` Segment、`4289` FRCSD Road。

## 4. 范围与体量

- 只修改 T12 算法、additive 输出及对应项目/T12 源事实；未修改
  T01–T11、T10 编排、正式入口或 CLI 参数。
- 受影响 `9` 个源码/测试文件均低于 `60KiB` 和 `100000 bytes`；
  最大为 `candidate_audit.py`（`52472 bytes`）。
- 用户指定的 `1074275_74421865`、`1100233_55068631`、
  `957702_957699` 仅存在于内网，仍需用同一 v8 入口做内网全量验收；
  本地结果不能替代内网结论。
