# 规格说明：T03 internal full-input 输出契约回写

## 1. 背景

`t03_virtual_junction_anchor` 当前已经形成可执行的内网 full-input 交付链：

- repo 级运行脚本：`scripts/t03_run_step67_internal_full_input_8workers.sh`
- repo 级监控脚本：`scripts/t03_watch_step67_internal_full_input.sh`
- 批次根目录正式成果：`virtual_intersection_polygons.gpkg`、`nodes.gpkg`

但 project-level / 治理级文档尚未完整登记这些事实，尤其缺少：

- internal full-input 已成为 T03 当前正式 repo 级脚本交付面
- 批次根目录正式成果的字段与语义边界
- `nodes.gpkg` 的代表 node 更新规则与 `fail3` 的 downstream-only 语义
- watch formal-first 口径的 project-level 登记

本规格只处理上述 project-level / 治理级回写，不扩展到模块文档正文或代码逻辑。

## 2. 目标

将 T03 internal full-input 的正式成果需求写入 project-level / 治理级文档，使项目级 source-of-truth 与当前 repo 级交付面保持一致。

## 3. 范围

### 3.1 包含

- `SPEC.md`
- `docs/PROJECT_BRIEF.md`
- `docs/repository-metadata/entrypoint-registry.md`
- `docs/doc-governance/current-doc-inventory.md`
- 本规格对应的 spec-kit 工件

### 3.2 不包含

- `modules/t03_virtual_junction_anchor/*` 正文改写
- `src/` 代码实现改动
- 几何逻辑、full-input 架构或 monitor 行为变更
- T02 上游契约改写

## 4. 正式需求

### FR-001：repo 级交付面登记

project-level 文档必须明确：

- `t03_run_step67_internal_full_input_8workers.sh`
- `t03_watch_step67_internal_full_input.sh`

是 T03 当前 internal full-input 的正式 repo 级脚本交付面。

该登记不得被误写为新的 repo 官方 CLI。

### FR-002：批次根目录正式成果登记

project-level 文档必须明确 T03 internal full-input 当前正式批次根目录成果至少包括：

- `virtual_intersection_polygons.gpkg`
- `nodes.gpkg`

并说明：

- `virtual_intersection_polygons.gpkg` 是批次级聚合虚拟路口面成果
- `nodes.gpkg` 是基于输入 full-input 整层 `nodes.gpkg` 输出的更新版结果

### FR-003：`nodes.gpkg` 更新规则登记

project-level 文档必须明确 `nodes.gpkg` 的更新规则：

- 仅更新代表 node
- `accepted => yes`
- `rejected / runtime_failed => fail3`
- 未选中 node 保持输入值不变

### FR-004：`fail3` 语义边界登记

project-level 文档必须明确：

- `fail3` 只属于 T03 downstream output 语义
- 不回写输入原始 `nodes.gpkg`
- 不反向修改 T02 上游契约

### FR-005：watch formal-first 登记

project-level 文档必须明确：

- `t03_watch_step67_internal_full_input.sh` 当前采用 formal-first 监控口径
- 默认按 T02 风格关注 `selected / completed / running / pending / accepted / rejected / runtime_failed / missing_status`
- 视觉层统计只属于 review-only 调试面

## 5. 非目标

- 不把 Step67 提升为新的 repo 官方 CLI
- 不将 `fail3` 推广为 T02 上游 `is_anchor` 契约值
- 不在本轮重新 formalize 模块级长文档
