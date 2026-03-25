# 当前模块盘点

## 范围

- 盘点日期：2026-03-22
- 目的：说明当前仓库正式业务模块现状、模块文档面状态与模板资产状态

## 当前正式生命周期结论

- `Active`：
  - `t02_junction_anchor`
- `Historical Reference`：无
- `Retired`：无
- `Support Retained`：无

## 当前 Active 模块

| 模块 ID | 路径 | 当前正式范围 | 当前文档面状态 | 当前实现状态 | 备注 |
|---|---|---|---|---|---|
| `t02_junction_anchor` | `modules/t02_junction_anchor` | stage1 `DriveZone / has_evd gate` + stage2 `anchor recognition / anchor existence`；单 `mainnodeid` 虚拟路口 / 文本证据包为受控实验入口 | 已补齐标准 architecture 文档组、`INTERFACE_CONTRACT.md`、`README.md`、`AGENTS.md` | stage1 / stage2 已实现；单 `mainnodeid` 虚拟路口与文本证据包已形成最小实验闭环 | T01 是其上游事实源之一；最终唯一锚定决策与全量批处理仍未进入当前正式范围 |

## 特殊模板资产

| 名称 | 路径 | 当前状态 | 当前定位 | 当前文档面状态 | 推荐动作 | 备注 |
|---|---|---|---|---|---|---|
| `_template` | `modules/_template` | `template-artifact` | 新模块启动模板 | 已提供标准文档契约骨架 | 后续新模块启动时复制并具体化 | 不属于业务模块生命周期 |

## 当前结论

1. 当前仓库已登记正式业务模块 `t02_junction_anchor`。
2. `_template` 仍是后续新模块启动模板，不属于业务模块生命周期对象。
3. 后续任何新增 RCSD 模块仍应先按模板建立文档契约，再进入实现阶段。
4. 未在本盘点中登记的模块目录，不自动视为 repo 级正式业务模块。
