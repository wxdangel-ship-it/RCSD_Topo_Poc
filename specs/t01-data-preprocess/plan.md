# T01 计划

## 当前阶段
- `formal flow consolidation with Step6 integration`

## 本轮目标
1. 将官方输入契约统一到 GeoJSON。
2. 将 roads 正式输出字段统一到 `sgrade / segmentid`。
3. 将 Step6 从独立 POC 正式纳入 official end-to-end。
4. 减少 Step6 与 Step1-Step5C 之间的重复读取、重复分组、重复邻接计算与重复写盘。
5. 更新 freeze compare，使其区分 schema migration difference 与真实业务回退。
6. 完成 `XXXS` 官方回归并给出结果解释。

## 本轮边界
- 不改 accepted 的 Step1-Step5C 业务语义。
- 不放松 `closed_con in {2,3}`、`road_kind != 1`、50m gates。
- 不重新设计 residual graph staged runner。
- 不 silently 更新 freeze baseline。

## 实施顺序
1. 调整 working road schema：`s_grade -> sgrade`，保留读取兼容。
2. 统一 CLI / README / 契约文档的 GeoJSON 官方输入口径。
3. 将 Step6 接到 official `t01-run-skill-v1` 的最终阶段。
4. 在 official runner 中复用 Step5 的内存态 records 和分组索引。
5. 更新 freeze compare 的 schema migration 兼容。
6. 运行定向测试与 `XXXS` 官方回归，确认业务结果不回退。
