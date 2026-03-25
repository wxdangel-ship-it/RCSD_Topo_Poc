# 模块生命周期

## 1. 文档目的

本文档用于定义本仓库业务模块的生命周期状态，明确哪些模块属于当前正式治理对象、哪些已经退役、哪些只保留为历史参考。

`modules/_template/` 不是业务模块，不纳入本生命周期表。

## 2. 状态定义

### Active

- 当前正式治理与迭代对象

### Retired

- 不再作为当前活跃模块治理对象
- 保留历史实现与文档

### Historical Reference

- 不再作为当前正式模块
- 保留为经验、历史证据和择优提炼来源

### Support Retained

- 仓库保留的支撑 / 测试模块
- 当前不属于活跃模块集合

## 3. 当前模块状态表

### Active

| 模块 ID | 路径 | 当前正式范围 | 当前状态 |
|---|---|---|---|
| `t02_junction_anchor` | `modules/t02_junction_anchor` | `DriveZone / has_evd gate` + `anchor recognition / anchor existence`；单 `mainnodeid` 虚拟路口 / 文本证据包为受控实验入口 | `stage1/stage2 active, experimental poc active` |

### Retired

当前无。

### Historical Reference

当前无。

### Support Retained

当前无。

说明：

- 未在本表登记的模块目录，不自动视为当前正式治理对象。
- `t02_junction_anchor` 当前已具备 stage1 与 stage2 的最小实现闭环。
- 单 `mainnodeid` 虚拟路口面与文本证据包当前属于受控实验入口，不等于最终唯一锚定决策闭环。

## 4. 模板目录说明

- `modules/_template/` 是模块启动模板
- 它不是 `Active`、`Retired`、`Historical Reference` 或 `Support Retained` 中的任何一种
- 不能把模板目录误当成已经存在的业务模块
