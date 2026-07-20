# Validation：T12 Road-surface portal

## 1. 目标 Segment 正式重放

三条本地可重放包均使用正式 T12 入口和 `EPSG:3857`，结果均为 `candidate=1 / confirmed=0 / excluded=1 / manual=0`，决策规则为 `equivalent_t07_road_surface_carrier`：

| Segment | 新判定 | 关键有向 Road 链 |
|---|---|---|
| `1623512_508276240` | 排除误报 | `5846232894805637 → 5846235376255196 → 5846062370914501 → 5846062370914538 → 5846062370914539 → 5846062370914482 → 5846062370914532 → 5846062370914533 → 5846318893236852` |
| `1921739_1921764` | 排除误报 | `5846239336988730 → 5846239336988881 → 5846239336988871 → 5846081866170510 → 5846081866170519 → 5846079383279186` |
| `500636195_505415445` | 排除误报 | 反向链在用户确认的 `5844526046380212 → 5844526046380039 → 5844526046380222 → 5844526046380213 → 5844524169041622` 停止；终点由 anchor→frontier support Road `5844524169041952` 证明标准面 access |

正式输出根目录：

- `outputs/_work/t12_road_surface_portal_20260720/official_replay/t12_1623512_508276240_surface_v4g`
- `outputs/_work/t12_road_surface_portal_20260720/official_replay/t12_1921739_1921764_surface_v4g`
- `outputs/_work/t12_road_surface_portal_20260720/official_replay/t12_500636195_505415445_surface_v4g`

## 2. `1026960` 冻结基线

原始数据正式重放根目录为 `outputs/_work/t12_road_surface_portal_20260720/baseline/t12_1026960_road_surface_v4f`：

- `candidate=35 / confirmed=10 / excluded=25 / manual=0`；
- confirmed `candidate_id + issue_type` 与变更前冻结集合逐项一致；
- issue type 仍为 `directed_carrier_missing=8`、`required_local_connectivity_missing=2`；
- 新 Road-surface 规则在该基线中没有排除任一冻结问题，`t07_road_surface_equivalent_candidate_count=0`。

实现早期曾把 `1019779_1026330` 错误排除，使 confirmed 降为 9。原始 Road 审计证明其 source support Road 方向为 frontier→anchor，不能证明从标准面向外的 portal。实现据此采用通用门禁：one-hop support 必须是 anchor→frontier、必须接触标准面或在固定 `1m` 拓扑容差内，且 carrier 至少一端存在真实 Road-surface contact。收紧后冻结集合恢复，不修改真值或 fixture。

## 3. GIS 与运行审计

- CRS：所有目标重放和基线均显式使用 metre-based `EPSG:3857`；各输入层 CRS 与 processing CRS 一致，未发生隐式变换。
- 拓扑：只在既有有向 Road 图上搜索；路径必须包含物理 Road，不创建虚拟 Road，不 snap、不 repair，`silent_fix=false`。
- 几何语义：标准面 access 仅允许 Road 与面实际相交，或受 anchor→frontier 一跳物理 Road 支撑；双 frontier 且无任何真实 surface contact 的路径被拒绝。
- 追溯：CSV/GPKG 记录 Road 序列、标准面 ID、access 类型、frontier、support Road、距离指标和风险标记；summary/manifest 记录输入哈希、参数、CRS、环境和输出路径。
- 完整性：`1026960` 的 invalid geometry 均为 0，FRCSD Road `4289`、Node `4762`，endpoint missing 为 0。
- 性能：`1026960` 总耗时 `6.255s`，其中 candidate audit `2.577s`；未发现相对旧正式重放的性能退化。

## 4. 自动化验证

- `tests/modules/t12_frcsd_quality_audit`：`43 passed`；
- T10 + T12 定向联合回归：`114 passed`；
- 生产源码和正式脚本对象 ID 扫描：0 命中；
- 本轮 10 个源码/脚本/测试文件均小于 100KB，最大 `candidate_audit.py=29673 bytes`；
- `git diff --check`：通过；
- 仓库全量单进程 pytest 因三个同名 `test_text_bundle.py` 的既有 collection collision 无法收集；改为分模块运行后，T02 自身出现 `21 failed / 394 passed / 4 skipped`。本轮未修改或依赖 T02，T12/T10 验收不使用这些失败作为通过证据，也不扩大范围修复 T02。

## 5. 结论

Road-surface portal 已作为通用、排除误报专用的 T12 正式规则接入。距离门禁只保留为审计风险，不会在双 T07 唯一标准面与物理方向拓扑已经成立时单独拒绝 carrier；长度比例和附加长度仍是硬门禁。三条目标误报已消除，`1026960` 的 10 条有效质量问题保持不变。
