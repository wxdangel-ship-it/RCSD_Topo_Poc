# T02 Architecture Overview

## 当前正式结构

- `T01 segment / nodes`
- `DriveZone`
- `RCSDIntersection`
- `roads / RCSDRoad / RCSDNode`
- `t02-stage1-drivezone-gate`
- `t02-stage2-anchor-recognition`
- `t02-virtual-intersection-poc`
- `t02-export-text-bundle / t02-decode-text-bundle`
- `nodes.geojson / segment.geojson`
- `summary`
- `audit / log`

## 当前正式阶段

- stage1：`DriveZone / has_evd gate`
- stage2：`anchor recognition / anchor existence`（最小闭环已实现）
- stage3：`virtual intersection anchoring`
- 支撑工具：单 `mainnodeid` 文本证据包

## 当前主原则

- T02 当前是正式模块；当前正式 baseline 闭环覆盖 stage1、stage2 与 stage3。
- stage1 负责资料存在性 gate，并在 `summary` 中输出分桶统计与 `all__d_sgrade` 总汇总。
- stage2 当前已落地 `RCSDIntersection`、`is_anchor`、`fail1/fail2` 与阶段边界的最小实现闭环，不等于最终锚定闭环。
- stage3 负责虚拟路口面锚定，当前官方入口统一为 `t02-virtual-intersection-poc`。
- 文本证据包只承担 stage3 复核与外部复现支撑，不构成新的业务阶段。
- 长期模块真相以 `architecture/*` 与 `INTERFACE_CONTRACT.md` 为准。
- `README.md` 只承担操作者入口说明。
- `specs/t02-junction-anchor/*` 与 `specs/t02-virtual-intersection-batch-poc/*` 是变更工件，不替代长期模块真相。

## 推荐阅读顺序

1. `01-introduction-and-goals.md`
2. `02-constraints.md`
3. `04-solution-strategy.md`
4. `05-building-block-view.md`
5. `INTERFACE_CONTRACT.md`
6. `10-quality-requirements.md`
