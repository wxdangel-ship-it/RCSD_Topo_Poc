# T02 Architecture Overview

## 当前正式结构

- `T01 segment / nodes`
- `DriveZone`
- `t02-stage1-drivezone-gate`
- `nodes.geojson / segment.geojson`
- `summary`
- `audit / log`

## 当前正式阶段

- stage1：`DriveZone / has_evd gate`
- stage2：anchoring 主逻辑（占位，未实现）

## 当前主原则

- T02 当前是正式模块，但正式实现范围只到 stage1。
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
