# RCSD_Topo_Poc - Project Brief (Global)

## 1. 项目目标

`RCSD_Topo_Poc` 当前阶段的目标是在保留工程底座治理的同时，开始承载正式业务模块。当前重点包括：

- 仓库骨架
- 文档治理与 source-of-truth 分层
- RCSD-neutral 的文本回传协议
- 新模块启动模板
- 基础测试与 smoke 模式
- 已登记正式模块的文档契约与实现收口

## 2. 当前范围

- 初始化 `docs/`、`modules/`、`src/`、`tests/`、`tools/`、`configs/` 等顶层骨架
- 建立项目级架构文档与仓库结构元数据
- 建立 `modules/_template/` 作为后续模块统一起点
- 保持当前输入数据组织方式与 `Highway_Topo_Poc` 一致
- 维护当前已登记正式模块 `t02_junction_anchor`

## 3. 当前非目标

- 不无边界扩展更多未登记业务模块
- 不迁移 Highway 的算法实现、专项脚本与历史审计工件
- 不冻结 RCSD 的模块列表、指标口径与执行链路

## 4. 当前结构性结论

- 当前已登记正式业务模块：`t02_junction_anchor`
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
