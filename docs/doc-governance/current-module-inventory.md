# 当前模块盘点

## 范围

- 盘点日期：2026-04-18
- 目的：说明当前仓库正式业务模块现状、模块文档面状态与模板资产状态

## 当前正式生命周期结论

- `Active`：
  - `t01_data_preprocess`
  - `t02_junction_anchor`
  - `t03_virtual_junction_anchor`
  - `t04_divmerge_virtual_polygon`
- `Historical Reference`：无
- `Retired`：无
- `Support Retained`：
  - `t00_utility_toolbox`

## 当前 Active 模块

| 模块 ID | 路径 | 当前正式范围 | 当前文档面状态 | 当前实现状态 | 备注 |
|---|---|---|---|---|---|
| `t01_data_preprocess` | `modules/t01_data_preprocess` | working bootstrap + roundabout preprocessing + Step1-Step6 双向 Segment 构建 official end-to-end；active freeze compare 为 `t01_skill_active_eight_sample_suite` | 已补齐标准 architecture 文档组、`INTERFACE_CONTRACT.md`、`README.md`、`AGENTS.md` | `t01-run-skill-v1` 与 `t01-compare-freeze` 已正式可用；Step6 已纳入 official end-to-end | 当前正式范围聚焦非封闭式双向道路；单向 Segment 与更大批处理扩展未纳入当前正式范围 |
| `t02_junction_anchor` | `modules/t02_junction_anchor` | stage1 `DriveZone / has_evd gate` + stage2 `anchor recognition / anchor existence` + stage3 `virtual intersection anchoring` baseline；文本证据包与 `t02-fix-node-error-2` 为独立支撑入口 | 已补齐标准 architecture 文档组、`06-accepted-baseline.md`、`INTERFACE_CONTRACT.md`、`README.md`、`AGENTS.md` | stage1 / stage2 / stage3 已实现；`t02-virtual-intersection-poc` 已支持 `case-package` 唯一正式验收基线与 `full-input` 完整数据 `fixture / dev-only / regression` 模式 | T01 是其上游事实源之一；模块正文可在独立重构轮次中维护，本盘点只保留项目级登记与入口索引 |
| `t03_virtual_junction_anchor` | `modules/t03_virtual_junction_anchor` | 冻结 `Step3 legal-space baseline` + `Step4-7 clarified formal stage`；Anchor61 `case-package` 输入、Step3 prerequisite、Step45 中间结果包、Step67 二态发布结果、平铺 PNG 审查目录与索引汇总 | 已补齐标准 architecture 文档组、`INTERFACE_CONTRACT.md`、`README.md`、`AGENTS.md` | `t03-step3-legal-space` 作为冻结前置入口保留，`t03-step45-rcsd-association` 为当前正式 CLI；`Step67` 已形成正式交付与 closeout，但未提升为 repo 官方 CLI | 继承 T02 正式契约，不继承 T02 的 cleanup/trim 结构债；当前剩余 `707913 / 954218 / 520394575` 已人工确认属于输入数据错误 |
| `t04_divmerge_virtual_polygon` | `modules/t04_divmerge_virtual_polygon` | `Step1-4` doc-first formalization；case-package 输入、admission/local-context/topology/event-unit interpretation、Step4 overview/event-unit review、flat mirror、index、summary | 已补齐标准 architecture 文档组、`INTERFACE_CONTRACT.md`、`README.md`、`AGENTS.md` | T04 Step1-4 runner 已模块化实现，优先复用 T02 Stage4 内核与 T03 review closeout 组织，不新增 repo 官方 CLI | 当前仅正式覆盖 Step1-4；Step5-7 仍留待后续轮次承接 |

## 当前 Support Retained 模块

| 模块 ID | 路径 | 当前正式范围 | 当前文档面状态 | 当前实现状态 | 备注 |
|---|---|---|---|---|---|
| `t00_utility_toolbox` | `modules/t00_utility_toolbox` | Tool1-Tool9 固定脚本与共享底层能力；项目内工具集合，不直接承担业务生产逻辑 | 已具备 `architecture/*`、`INTERFACE_CONTRACT.md`、`README.md`、`AGENTS.md` | root `scripts/` 下固定工具脚本可用 | 纳入治理，但不计入 Active 业务模块集合 |

## 特殊模板资产

| 名称 | 路径 | 当前状态 | 当前定位 | 当前文档面状态 | 推荐动作 | 备注 |
|---|---|---|---|---|---|---|
| `_template` | `modules/_template` | `template-artifact` | 新模块启动模板 | 已提供标准文档契约骨架 | 后续新模块启动时复制并具体化 | 不属于业务模块生命周期 |

## 当前结论

1. 当前仓库已登记正式业务模块 `t01_data_preprocess`、`t02_junction_anchor`、`t03_virtual_junction_anchor` 与 `t04_divmerge_virtual_polygon`。
2. `t00_utility_toolbox` 已纳入治理，定位为工具集合模块 / 非业务生产模块。
3. `_template` 仍是后续新模块启动模板，不属于业务模块生命周期对象。
4. 后续任何新增 RCSD 模块仍应先按模板建立文档契约，再进入实现阶段。
5. 未在本盘点中登记的模块目录，不自动视为 repo 级正式治理对象。
