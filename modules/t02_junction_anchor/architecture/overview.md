# T02 Architecture Overview

> 当前项目级生命周期中，T02 已 Retired。本文档保留退役前架构概览，用于解释历史实现、历史入口和旧 baseline，不代表当前主业务链的正式模块结构。

## 历史正式结构

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

## 历史正式阶段

- stage1：`DriveZone / has_evd gate`
- stage2：`anchor recognition / anchor existence`（最小闭环已实现）
- stage3：`virtual intersection anchoring`
- 支撑工具：单 `mainnodeid` 文本证据包、`t02-fix-node-error-2`

## 历史主原则

- T02 曾作为正式模块运行，历史 baseline 闭环覆盖 stage1、stage2 与 stage3；当前主业务链已由 T07 / T03 / T04 / T08 承接。
- `06-accepted-baseline.md` 是 T02 历史需求对齐与 accepted baseline 主文档。
- stage1 负责资料存在性 gate，并在 `summary` 中输出分桶统计与 `all__d_sgrade` 总汇总。
- stage2 历史上已落地 `RCSDIntersection`、`is_anchor`、`fail1/fail2` 与阶段边界的最小实现闭环，不等于最终锚定闭环。
- stage3 负责虚拟路口面锚定，历史官方入口统一为 `t02-virtual-intersection-poc`。
- 文本证据包只承担 stage3 复核与外部复现支撑，不构成新的业务阶段。
- 历史模块真相以 `architecture/*` 与 `INTERFACE_CONTRACT.md` 为准。
- `README.md` 只承担操作者入口说明。
- `specs/t02-junction-anchor/*` 与 `specs/t02-virtual-intersection-batch-poc/*` 是变更工件，不替代历史模块真相。

## 推荐阅读顺序

1. `06-accepted-baseline.md`
2. `07-stage3-business-requirements.md`
3. `08-stage3-algorithm-strategy.md`
4. `01-introduction-and-goals.md`
5. `02-constraints.md`
6. `03-solution-strategy.md`
7. `05-building-block-view.md`
8. `INTERFACE_CONTRACT.md`
9. `10-quality-requirements.md`
