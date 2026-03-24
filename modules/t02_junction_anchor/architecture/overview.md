# T02 Architecture Overview

## 当前正式结构

- `T01 segment / nodes`
- `DriveZone`
- `RCSDIntersection`
- `t02-stage1-drivezone-gate`
- `nodes.geojson / segment.geojson`
- `summary`
- `audit / log`

## 当前正式阶段

- stage1：`DriveZone / has_evd gate`
- stage2：anchor recognition / anchor existence 基线（文档冻结，未实现）

## 当前主原则

- T02 当前是正式模块，但正式实现范围只到 stage1。
- stage1 负责资料存在性 gate，并在 `summary` 中输出分桶统计与 `all__d_sgrade` 总汇总。
- stage2 当前只冻结 `RCSDIntersection`、`is_anchor`、`fail1/fail2` 与阶段边界，不等于最终锚定闭环。
- 长期模块真相以 `architecture/*` 与 `INTERFACE_CONTRACT.md` 为准。
- `README.md` 只承担操作者入口说明。
- `specs/t02-junction-anchor/*` 是变更工件，不替代长期模块真相。

## 推荐阅读顺序

1. `01-introduction-and-goals.md`
2. `02-constraints.md`
3. `04-solution-strategy.md`
4. `05-building-block-view.md`
5. `INTERFACE_CONTRACT.md`
6. `10-quality-requirements.md`
