# 08 横切概念

## 1. Source-of-Truth 分层

- 项目级 source-of-truth：`SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/architecture/*`、`docs/doc-governance/module-lifecycle.md`
- 项目级盘点 / 索引：`docs/doc-governance/current-module-inventory.md`、`docs/doc-governance/current-doc-inventory.md`、`docs/doc-governance/module-doc-status.csv`
- 模块级 source-of-truth：`modules/<module>/architecture/*`、`modules/<module>/INTERFACE_CONTRACT.md`
- durable guidance：`AGENTS.md`
- workflow：repo root `.agents/skills/<skill-name>/SKILL.md`

## 2. 文本回传协议

- 统一使用 `TEXT_QC_BUNDLE`
- 统一采用粘贴性守卫：`<= 120 行` 或 `<= 8KB`
- 超限时必须截断并明确标注

## 3. 文档与实现分层

- `modules/` 放文档入口与历史资料
- `src/rcsd_topo_poc/modules/` 放实现
- `tests/` 放测试
- `tools/` 放仓库级迁移、验证与 QA 工具

## 4. 模块启动模板

- `modules/_template/` 是统一模板
- 新模块启动先复制模板并完成文档契约
- 不先建实现，再补文档

## 5. 执行入口治理

- 默认禁止新增新的执行入口脚本
- 新增入口必须先证明现有入口不可复用
- 新增后必须登记到入口注册表
