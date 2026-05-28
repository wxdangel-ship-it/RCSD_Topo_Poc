# 文档治理入口

## 从哪里开始看

如果你是从 repo root `AGENTS.md` 进入这里，按以下顺序继续：

1. `SPEC.md`
2. `docs/PROJECT_BRIEF.md`
3. `docs/doc-governance/module-lifecycle.md`
4. `docs/doc-governance/current-module-inventory.md`
5. `docs/doc-governance/current-doc-inventory.md`
6. 只有在需要理解仓库结构、入口、文件体量与目录角色时，再进入 `docs/repository-metadata/README.md`
7. 如需启动新模块，再进入 `modules/_template/`

说明：

- 本页是治理主入口，不是项目级 source-of-truth 的替代面。
- `docs/repository-metadata/README.md` 是按需结构入口，不是并列 day-0 主入口。
- `specs/*`、`outputs/*`、`.claude/worktrees/*`、`.venv/*` 不属于 day-0 主阅读路径。

## 当前治理链路

- 仓库级执行规则：`AGENTS.md`
- 项目级源事实：
  - `SPEC.md`
  - `docs/PROJECT_BRIEF.md`
  - `docs/architecture/*`
  - `docs/doc-governance/module-lifecycle.md`
- 项目级盘点 / 索引：
  - `docs/doc-governance/current-module-inventory.md`
  - `docs/doc-governance/current-doc-inventory.md`
  - `docs/doc-governance/module-doc-status.csv`

## 当前模块状态简表

- Active 正式业务模块：
  - `t01_data_preprocess`
  - `t02_junction_anchor`
  - `t03_virtual_junction_anchor`
  - `t04_divmerge_virtual_polygon`
  - `t05_junction_surface_fusion`
  - `t06_segment_fusion_precheck`
  - `t07_semantic_junction_anchor`
  - `t08_preprocess`
  - `p01_arm_build`
- Support Retained：
  - `t00_utility_toolbox`
- 模板目录：
  - `modules/_template/`

说明：

- `_template` 仅用于后续模块启动，不属于业务模块生命周期盘点对象。
- `t00_utility_toolbox` 纳入治理，但定位为工具集合模块 / 非业务生产模块。
- `t02_junction_anchor` 当前仍是 Active 模块；其模块正文若处于独立重构中，应以该轮任务边界为准，不在其它治理轮次中顺手改写。
- `t03_virtual_junction_anchor` 当前进入 Active 模块集合；其正式业务主链按 `Step1~Step7` 表达，覆盖 case 受理、模板归类、合法空间冻结、RCSD 关联、foreign / excluded 负向约束、受约束几何与最终发布。
- `t03_virtual_junction_anchor` 当前 repo 官方入口保留 `t03-step3-legal-space` 与 `t03-rcsd-association`；`Association / Finalization` 只作为实现阶段与输出命名保留，不再作为正式需求主结构。
- `t04_divmerge_virtual_polygon` 当前进入 Active 模块集合；其正式范围为 `Step1-7` 的模块化实现、Step7 发布层与 internal full-input repo 级脚本包装；不新增 repo 官方 CLI 子命令。
- `t05_junction_surface_fusion` 当前进入 Active 模块集合；其正式范围覆盖 Phase 1 路口面融合发布与 Phase 2 RCSD junctionization / SWSD-RCSD relation 生产，Phase 2 以 copy-on-write 输出表达 RCSD 网络变化。
- `t06_segment_fusion_precheck` 当前进入 Active 模块集合；其正式范围扩展为 Step1 SWSD 可融合 Segment 识别、Step2 buffer-based RCSDSegment 构建、兼容可替换集合和错误分析，以及 Step3 基于 replaceable Segment 的 F-RCSD Road / Node 输出与语义路口关系重建；Step3 提供模块内 callable runner 与独立脚本。
- `t07_semantic_junction_anchor` 当前进入 Active 模块集合；其正式范围仅覆盖 T02 Step1 / Step2 的语义路口级重构，输出代表 node 的 `has_evd / is_anchor / anchor_reason`，只消费 `nodes / DriveZone / RCSDIntersection`，不处理 Segment，并通过模块内 callable runner 与 `scripts/t07_run_semantic_junction_anchor_innernet.sh` 执行。
- `t08_preprocess` 当前进入 Active 模块集合；其正式范围覆盖 Tool1 基础矢量格式转换、Tool2 Road GPKG 预处理、Tool3 Nodes 类型聚合、Tool4 路口类型错误识别与 Tool5 复杂路口预处理，Tool1 支持 SHP / GeoJSON 转 GPKG 与 GPKG 转 GeoJSON，输出均写回输入目录下同名文件，Tool2 补充 `patch_id / kind`，Tool3 补充 `kind_2 / grade_2` 并处理环岛 mainnode，Tool4 输出 `nodes_error.gpkg` 记录错误类型，Tool5 构建复杂分歧 / 合流路口并可处理错误 1 对多路口，输出 `EPSG:3857` GPKG；Tool4 不执行自动修复。
- `p01_arm_build` 当前进入 Active 模块集合；其正式范围为 P01-A1 Arm 构建、P01-A2 Arm 配准与 P01-Final F-RCSD RoadNextRoad 还原，当前仅提供模块内可调用 runner，不提供 repo 官方 CLI 子命令或 `scripts/` 常驻命令。
- 未在模块生命周期文档中登记的模块目录，不自动视为当前正式治理对象。

## 哪些文档不是主入口

- `docs/doc-governance/history/`：仓库级历史治理过程材料
- `docs/archive/nonstandard/`：项目级非标准历史说明
- `specs/*`：spec-kit 变更工件
- `outputs/*`：运行与审计工件

这些位置可以用于追溯与审计，但不替代当前项目级或模块级源事实。
