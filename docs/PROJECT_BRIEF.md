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
- 维护当前已登记正式模块 `t04_divmerge_virtual_polygon`

## 3. 当前非目标

- 不无边界扩展更多未登记业务模块
- 不迁移 Highway 的算法实现、专项脚本与历史审计工件
- 不冻结 RCSD 的模块列表、指标口径与执行链路

## 4. 当前结构性结论

- 当前已登记正式业务模块：`t01_data_preprocess`、`t02_junction_anchor`、`t03_virtual_junction_anchor`、`t04_divmerge_virtual_polygon`
- 当前已纳入治理的工具集合模块：`t00_utility_toolbox`
- `t00_utility_toolbox` 的定位是工具集合模块 / 非业务生产模块
- `t01_data_preprocess` 当前已具备 official end-to-end、Step6 聚合与 freeze compare 的最小实现闭环
- `t02_junction_anchor` 当前仍为 Active 正式业务模块；模块正文如在独立重构中，应在独立轮次中维护
- `t03_virtual_junction_anchor` 当前仍为 Active 正式业务模块；正式范围按 `Step1~Step7` 业务主链表达，仅处理 `center_junction / single_sided_t_mouth`，默认正式全量 `58` case 的业务正确性基线已满足人工目视审计
- `t03_virtual_junction_anchor` 当前少量 accepted case 仍存在几何形状优化空间，但这属于后续长期迭代方向，不再构成当前正式准出阻塞项
- `t03_virtual_junction_anchor` 当前仍保留历史命名的 `t03-step45-rcsd-association` 官方 CLI；其业务含义对应 `Step4 + Step5`，`Step45 / Step67` 不再作为正式需求主结构。T03 模块级内网批量执行与监控已经形成 repo 级脚本交付面：主脚本为 `scripts/t03_run_internal_full_input_8workers.sh` 与 `scripts/t03_watch_internal_full_input.sh`，旧 `step67` 脚本名仅保留兼容 wrapper
- `t03_virtual_junction_anchor` 当前 internal full-input 批次根目录正式成果包括 `virtual_intersection_polygons.gpkg` 与 `nodes.gpkg`
- `t03_virtual_junction_anchor` 当前 `nodes.gpkg` 仅更新代表 node 的 `is_anchor`：`accepted => yes`，`rejected / runtime_failed => fail3`；其中 `fail3` 只属于 T03 downstream output 语义，不回写输入原始 `nodes.gpkg`，也不反向修改 T02 上游契约
- `t03_watch_internal_full_input.sh` 当前采用 T02 风格的 formal-first 监控口径，默认关注 `total / completed / running / pending / success / failed`
- `t04_divmerge_virtual_polygon` 当前作为 Active 正式业务模块进入治理；正式范围已扩展到 `Step1-7`，其中 `Step1-4` 维持既有 `case-package` 输入下的 Step4 review PNG、flat mirror、index 与 summary，`Step5-7` 进入正式研发实现阶段，且默认遵循 SpecKit 的 `Product / Architecture / Development / Testing / QA` 五视角覆盖；internal full-input 通过 repo 级 shell/watch 包装 + T04 私有 runner 交付，不新增 repo 官方 CLI
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
