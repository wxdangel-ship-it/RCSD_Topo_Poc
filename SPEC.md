# SPEC：RCSD 场景路网拓扑 POC 需求说明（RCSD_Topo_Poc）

- 文档类型：需求规格说明（Specification）
- 项目名称：RCSD_Topo_Poc
- 版本：v0.1
- 状态：Draft
- 当前阶段：仓库骨架已建立，进入工程治理与已登记模块并行维护阶段
- 交付形态：外网 GitHub 仓库 + 内网执行 + 文本粘贴回传

---

## 1. 项目概述

`RCSD_Topo_Poc` 的目标是为 RCSD 场景下的路网拓扑相关能力建立一个可持续迭代的工程底座，并在此基础上承载正式业务模块。当前阶段在延续基础工程治理的同时，已经进入“工程治理 + 已登记模块并行维护”阶段：

- 仓库级骨架
- 文档治理与 source-of-truth 分层
- 共享文本回传协议
- 模块启动标准模板
- `src/`、`modules/`、`tests/`、`tools/` 的基础边界
- 当前已登记正式业务模块 `t01_data_preprocess`
- 当前已登记正式业务模块 `t02_junction_anchor`
- 当前已登记正式业务模块 `t03_virtual_junction_anchor`
- 当前已纳入治理的工具集合模块 `t00_utility_toolbox`

当前原则是优先复用 `Highway_Topo_Poc` 中已经验证有效的仓库骨架、治理方式与协作约束，但不迁移任何高速场景业务模块实现。

---

## 2. 当前阶段目标

### 2.1 当前阶段必须完成

- 建立 RCSD 的 git 工作副本与基础工程骨架
- 固化项目级 `AGENTS.md`、`SPEC.md`、`docs/PROJECT_BRIEF.md`
- 建立项目级 `docs/architecture/*`、`docs/doc-governance/*`、`docs/repository-metadata/*`
- 建立 RCSD-neutral 的 `TEXT_QC_BUNDLE` 协议、粘贴性守卫与基础测试
- 建立 `modules/_template/`，用于后续任何新模块的标准启动
- 让已登记模块的文档面、实现入口与测试面保持一致
- 让 `t00_utility_toolbox` 维持工具集合模块 / 非业务生产模块边界
- 让 `t01_data_preprocess` 的 accepted baseline、官方入口与 freeze compare 口径保持一致
- 让 `t02_junction_anchor` 的项目级登记状态与仓库级入口事实保持一致
- 让 `t03_virtual_junction_anchor` 的冻结 `Step3 legal-space baseline`、`Step4-7 clarified formal stage` 与仓库级入口事实保持一致
- 让 `t03_virtual_junction_anchor` 的 internal full-input repo 级脚本交付面、批次根目录正式成果与 project-level 文档登记保持一致

### 2.2 当前阶段明确不做

- 不无边界扩展更多未登记的 RCSD 业务模块
- 不迁移 `Highway_Topo_Poc` 的算法实现、专项脚本、专项审计工件
- 不冻结 RCSD 的业务指标、阈值、模块列表和执行链路

---

## 3. 范围与非目标

### 3.1 当前范围（包含）

- 仓库骨架初始化
- 项目级治理规则与文档入口
- 模块级启动模板
- 文本回传协议与其最小共享代码
- 基础测试与 smoke 模式
- `t00_utility_toolbox` 作为工具集合模块的治理与固定脚本入口
- 已登记正式模块 `t01_data_preprocess` 的 accepted baseline、official end-to-end 与 freeze compare
- 已登记正式模块 `t02_junction_anchor` 的项目级登记状态与仓库级入口索引
- 已登记正式模块 `t03_virtual_junction_anchor` 的冻结 `Step3 legal-space baseline`、`Step4-7 clarified formal stage`、repo 级 internal full-input shell/watch 交付面、批量审查产物与入口索引

### 3.2 当前非目标（不包含）

- 未登记业务模块的无边界实现
- RCSD 模块级算法、参数与验收阈值
- 历史数据迁移、真实数据接入或专项回归链路
- 任何 Highway 模块正文、历史审计材料或专项评估脚本的整包平移

---

## 4. 关键约束与假设

### 4.1 复用方式约束

- 只复用骨架、治理规则、文档契约体系与协作方式。
- 业务正文、算法实现、专项脚本、专项术语不复用。
- 模块根目录不放 `SKILL.md`；标准 Skill 统一放 repo root `.agents/skills/`。

### 4.2 数据组织假设

当前输入数据组织方式先与 `Highway_Topo_Poc` 保持一致，作为初始兼容布局；这只是当前阶段的输入组织约束，不等于 RCSD 业务标准已经冻结。

初始兼容布局为：

```text
<PatchID>/
  PointCloud/
    *.laz
  Vector/
    LaneBoundary.geojson
    DivStripZone.geojson
    RCSDNode.geojson
    intersection_l.geojson
    RCSDRoad.geojson
  Tiles/
    <z>/<x>/<y>.<ext>
  Traj/
    <TrajID>/
      raw_dat_pose.geojson
```

### 4.3 工程与协作约束

- 项目内文档默认中文。
- 内网与外网默认执行环境均为 WSL。
- 项目工作目录默认使用 WSL 路径，例如 `/mnt/e/Work/RCSD_Topo_Poc`。
- 若上游输入或任务书给出 Windows 路径，应先转换为对应的 WSL 路径再执行。
- 文档在 `modules/<module>/`，实现代码在 `src/rcsd_topo_poc/modules/<module>/`。
- 运行输出写入 `outputs/_work/`，不把输出目录当工作区。

### 4.4 T03 internal full-input 交付约束

- `t03_virtual_junction_anchor` 当前除 `Step4-5` 官方 CLI 外，还存在 repo 级 internal full-input shell/watch 交付面：`scripts/t03_run_step67_internal_full_input_8workers.sh` 与 `scripts/t03_watch_step67_internal_full_input.sh`；它们属于 repo 级脚本入口，不构成新的 repo 官方 CLI。
- T03 internal full-input 当前正式批次根目录成果至少包括 `virtual_intersection_polygons.gpkg` 与 `nodes.gpkg`；前者聚合当前批次 case 级最终虚拟路口面，后者基于 full-input 输入的整层 `nodes.gpkg` 输出更新版结果。
- `nodes.gpkg` 的 `is_anchor=fail3` 只属于 T03 downstream output 语义：仅更新代表 node，`accepted => yes`，`rejected / runtime_failed => fail3`；该语义不回写输入原始 `nodes.gpkg`，也不反向修改 T02 上游契约。
- `t03_watch_step67_internal_full_input.sh` 当前采用 T02 风格的 formal-first 监控口径：默认显示 `selected / completed / running / pending / accepted / rejected / runtime_failed / missing_status`，并显式表达是否已进入 `case execution` 阶段；视觉层统计仅在显式调试场景下读取 review-only 工件。

---

## 5. 协作与治理方式

- 项目采用 spec-driven / SpecKit 风格工作流。
- 项目级真相写入 `SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/architecture/*`。
- 模块级真相写入 `modules/<module>/architecture/*` 与 `INTERFACE_CONTRACT.md`。
- `AGENTS.md` 只承载 durable guidance。
- `review-summary.md` 只承担治理摘要，不替代源事实。
- 历史资料进入 `history/` 或仓库级归档位置，不占据主阅读路径。

---

## 6. 当前仓库交付基线

当前仓库初始化后，至少包含：

- 项目级治理文档与架构文档
- `src/rcsd_topo_poc/` 包骨架
- RCSD-neutral 的文本回传协议与粘贴性守卫
- `tests/` 中对应的最小协议测试与 smoke
- `modules/_template/` 新模块启动模板

---

## 7. 模块启动标准

后续任何新模块启动时，Day-0 最少应创建：

- `AGENTS.md`
- `INTERFACE_CONTRACT.md`
- `architecture/01-introduction-and-goals.md`
- `architecture/03-context-and-scope.md`
- `architecture/04-solution-strategy.md`

建议在模块进入稳定执行前尽早补齐：

- `README.md`
- `architecture/02-constraints.md`
- `architecture/05-building-block-view.md`
- `architecture/10-quality-requirements.md`
- `architecture/11-risks-and-technical-debt.md`
- `architecture/12-glossary.md`

按模块成熟度和治理需要补充：

- `review-summary.md`
- `history/`
- `scripts/`

说明：

- repo root `.agents/skills/<skill-name>/SKILL.md` 属于仓库级可复用流程资产，不属于模块根 Day-0 文档集。
- 模块默认应复用 repo-level CLI 或 root `scripts/` 入口；若要新增模块局部执行入口，必须先满足 repo root `AGENTS.md` 的入口治理规则并登记。

---

## 8. 测试与可复现要求

- 默认测试框架为 `pytest`。
- 允许定义 `smoke` marker，约束其只写 `outputs/_work/`。
- 共享协议与粘贴性守卫必须有可执行测试。
- 当前阶段要求已登记正式模块的 stage1 / stage2 / stage3 baseline 与必要支撑入口具备最小单测与 smoke。

---

## 9. 当前结论

- RCSD 当前已从纯骨架阶段进入“工程治理 + 正式业务模块并行”阶段。
- 当前已登记正式业务模块：`t01_data_preprocess`、`t02_junction_anchor`、`t03_virtual_junction_anchor`。
- 当前已纳入治理的工具集合模块：`t00_utility_toolbox`，其定位为非业务生产模块。
- `t01_data_preprocess` 当前已具备 official end-to-end、Step6 聚合与 freeze compare 的最小闭环。
- `t02_junction_anchor` 当前仍是 Active 正式业务模块；其模块正文可在独立轮次中维护，但项目级登记与仓库级入口必须保持一致。
- `t03_virtual_junction_anchor` 当前作为 Active 正式业务模块；当前正式范围为“冻结 `Step3 legal-space baseline` + `Step4-7 clarified formal stage（仅 `center_junction / single_sided_t_mouth`）`”，默认正式全量 `58` case 的业务正确性基线已满足人工目视审计，少量 accepted case 的几何形状优化保留为长期迭代方向。
- `t03_virtual_junction_anchor` 当前仍只有 `Step4-5` 官方 CLI；`Step67` 已有正式交付与 closeout，但未提升为 repo 官方 CLI。其内网批量执行与监控当前通过 repo 级 `t03_run_step67_internal_full_input_8workers.sh` / `t03_watch_step67_internal_full_input.sh` 交付。
- `t03_virtual_junction_anchor` 的 internal full-input 当前正式批次根目录成果包括 `virtual_intersection_polygons.gpkg` 与 `nodes.gpkg`；其中 `nodes.gpkg` 仅更新代表 node，`fail3` 只代表 T03 downstream output 语义。
- 未来新增模块必须先按模板建文档契约，再进入实现阶段。
