# 实施计划：T03 internal full-input 输出契约回写

## 1. 实施策略

本轮采用最小治理变更策略：

1. 先在 spec-kit 中冻结变更范围、正式需求与非目标
2. 再回写 project-level / 治理级 source-of-truth
3. 最后做写集内一致性复核

不改模块文档正文，不改代码，不新增入口。

## 2. 角色拆分（多 Agent 视角）

### Agent-Project

负责：

- `SPEC.md`
- `docs/PROJECT_BRIEF.md`

目标：

- 把 T03 internal full-input repo 级交付面与批次根目录成果写回项目级真相
- 保持“Step67 仍无 repo 官方 CLI”的边界不被破坏

### Agent-Governance

负责：

- `docs/repository-metadata/entrypoint-registry.md`
- `docs/doc-governance/current-doc-inventory.md`

目标：

- 把 run/watch 脚本的正式交付语义登记为 repo 级入口事实
- 把批次根目录成果与 `fail3` downstream-only 语义登记到治理盘点

### Agent-SpecKit

负责：

- `specs/t03-internal-full-input-output-contract/spec.md`
- `plan.md`
- `tasks.md`

目标：

- 冻结本轮范围、约束、需求与任务清单
- 记录 residual gap，避免把本轮扩写成模块文档或代码轮次

## 3. 实施步骤

1. 读取当前 project-level / 治理级相关文档
2. 对照当前已登记入口事实，确认无 source-of-truth 冲突
3. 创建 spec-kit 目录与 3 个工件
4. 回写 4 份项目/治理文档
5. 复核写集内：
   - `Step67` 仍无 repo 官方 CLI
   - run/watch 为 repo 级脚本交付面
   - `virtual_intersection_polygons.gpkg`、`nodes.gpkg` 已登记
   - `fail3` 被限制在 downstream output 语义

## 4. 风险与边界

- 当前仅回写 project-level / 治理级文档，不验证模块文档正文是否逐句同步。
- 若模块文档后续需要更细粒度描述，应在独立轮次中处理。
- 本轮不触碰代码与脚本实现，因此不承担运行行为修复责任。

## 5. 完成判定

满足以下条件即可视为本轮完成：

- 4 份 project-level / 治理文档均已登记新增事实
- spec-kit 工件完整存在
- 写集内无“Step67 被误写成 repo 官方 CLI”的冲突
- `fail3` downstream-only 边界被明确写出
