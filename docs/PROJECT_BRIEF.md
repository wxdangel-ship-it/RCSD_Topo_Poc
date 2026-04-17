# RCSD_Topo_Poc - Project Brief (Global)

## 1. 项目目标

`RCSD_Topo_Poc` 当前阶段的目标是在保留工程底座治理的同时，持续维护已登记模块。当前重点包括：

- 仓库骨架
- 文档治理与 source-of-truth 分层
- RCSD-neutral 的文本回传协议
- 新模块启动模板
- 基础测试与 smoke 模式
- 已登记模块的文档契约与实现收口
- 工具集合模块、正式业务模块与模板目录的角色边界对齐
- 已登记模块的官方入口、文档契约与项目级登记保持一致

## 2. 当前范围

- 初始化 `docs/`、`modules/`、`src/`、`tests/`、`tools/`、`configs/` 等顶层骨架
- 建立项目级架构文档与仓库结构元数据
- 建立 `modules/_template/` 作为后续模块统一起点
- 保持当前输入数据组织方式与 `Highway_Topo_Poc` 一致
- 维护当前已纳入治理的 `t00_utility_toolbox`
- 维护当前已登记正式模块 `t01_data_preprocess`
- 维护当前已登记正式模块 `t02_junction_anchor`
- 维护当前已登记正式模块 `t03_virtual_junction_anchor`

## 3. 当前非目标

- 不无边界扩展更多未登记业务模块
- 不迁移 Highway 的算法实现、专项脚本与历史审计工件
- 不冻结 RCSD 的模块列表、指标口径与执行链路

## 4. 当前结构性结论

- 当前已登记正式业务模块：`t01_data_preprocess`、`t02_junction_anchor`、`t03_virtual_junction_anchor`
- 当前已纳入治理的工具集合模块：`t00_utility_toolbox`
- `t00_utility_toolbox` 的定位是工具集合模块 / 非业务生产模块
- `t01_data_preprocess` 当前已具备 official end-to-end、Step6 聚合与 freeze compare 的最小实现闭环
- `t02_junction_anchor` 当前仍为 Active 正式业务模块；模块正文如在独立重构中，应在独立轮次中维护
- `t03_virtual_junction_anchor` 当前仍为 Active 正式业务模块；正式范围只到 Phase A / Step3 legal-space baseline only
- `_template` 仅是模板目录，不属于模块生命周期盘点对象
- 模块根目录不放 `SKILL.md`
- 标准 Skill 统一放 repo root `.agents/skills/`

## 5. 初始数据组织兼容约束

当前阶段，patch 输入目录先沿用以下兼容布局：

```text
<PatchID>/
  PointCloud/
  Vector/
  Tiles/
  Traj/
```

这只是初始化阶段的数据组织兼容约束，不代表 RCSD 业务标准已经冻结。
