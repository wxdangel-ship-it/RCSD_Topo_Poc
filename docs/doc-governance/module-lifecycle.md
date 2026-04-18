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
| `t01_data_preprocess` | `modules/t01_data_preprocess` | working bootstrap + roundabout preprocessing + Step1-Step6 双向 Segment 构建 official end-to-end；active freeze compare 为 `t01_skill_active_eight_sample_suite` | `official end-to-end / freeze-compare baseline active` |
| `t02_junction_anchor` | `modules/t02_junction_anchor` | `DriveZone / has_evd gate` + `anchor recognition / anchor existence` + `virtual intersection anchoring` baseline；文本证据包与 `t02-fix-node-error-2` 为独立支撑入口 | `stage1/stage2/stage3 baseline active / independent refactor may continue outside this governance round` |
| `t03_virtual_junction_anchor` | `modules/t03_virtual_junction_anchor` | 冻结 `Step3 legal-space baseline` + `Step4-7 clarified formal stage`；仅处理 `center_junction / single_sided_t_mouth`，消费 Anchor61 `case-package` 与 Step3 baseline run root，输出 `Step45 required/support/excluded` RCSD 中间结果包，以及 `Step67 accepted/rejected` 发布结果、平铺 PNG、索引与汇总 | `step67 clarified formal stage active / 58-case correctness baseline accepted / minor geometry refinement remains iterative / frozen-step3 prerequisite / no public step67 cli` |

### Retired

| 模块 ID | 路径 | 当前正式范围 | 当前状态 |
|---|---|---|---|
当前无。

### Historical Reference

当前无。

### Support Retained

| 模块 ID | 路径 | 当前正式范围 | 当前状态 |
|---|---|---|---|
| `t00_utility_toolbox` | `modules/t00_utility_toolbox` | Tool1-Tool9 固定脚本与共享底层能力；项目内工具集合，不直接承担业务生产逻辑 | `governed tooling module / non-business production` |

说明：

- 未在本表登记的模块目录，不自动视为当前正式治理对象。
- `t01_data_preprocess` 当前已具备 official end-to-end、Step6 聚合与 active freeze compare 的最小实现闭环。
- `t02_junction_anchor` 当前已具备 stage1、stage2 与 stage3 的最小实现闭环；其模块正文若在独立重构中，应在独立轮次维护。
- `t03_virtual_junction_anchor` 当前作为 T03 新模块进入 Active，正式范围为冻结 `Step3 legal-space baseline` 之上的 `Step4-7 clarified formal stage`，仅处理 `center_junction / single_sided_t_mouth`。
- stage3 `virtual intersection anchoring` 纳入当前 baseline，不等于最终唯一锚定决策闭环或正式产线闭环。
- 单 `mainnodeid` 文本证据包当前作为 stage3 复核与外部复现支撑入口保留。
- `t02-fix-node-error-2` 当前作为 stage2 之后的独立离线修复工具保留，不纳入主阶段链。
- `t00_utility_toolbox` 已纳入治理，但不属于业务生产模块，不应误记为 Active 业务模块。

## 4. 模板目录说明

- `modules/_template/` 是模块启动模板
- 它不是 `Active`、`Retired`、`Historical Reference` 或 `Support Retained` 中的任何一种
- 不能把模板目录误当成已经存在的业务模块
