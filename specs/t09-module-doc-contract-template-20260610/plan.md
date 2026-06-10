# T09 Module Documentation Surface And Contract Template Plan

## 1. 执行计划

1. 读取当前 T09 spec、实现公开 callable、输出对象和测试面。
2. 新增 T09 模块文档面。
3. 更新 `_template`，固化凝练版 / 详细版需求说明分工。
4. 同步项目级盘点中 T09 模块文档面状态。
5. 按用户授权最小同步 T10 中关于 T09 文档面缺失的过期引用。
6. 做文档格式和范围验证。

## 2. 文件范围

允许修改：

- `modules/t09_swsd_field_rule_restoration/**`
- `modules/_template/**`
- `docs/doc-governance/current-doc-inventory.md`
- `docs/doc-governance/current-module-inventory.md`
- `docs/doc-governance/module-lifecycle.md`
- `docs/doc-governance/module-doc-status.csv`
- `SPEC.md`
- `docs/PROJECT_BRIEF.md`
- `docs/architecture/06-risks-and-technical-debt.md`
- `modules/t10_e2e_orchestration/INTERFACE_CONTRACT.md`（仅 T09 文档面状态过期引用）
- `modules/t10_e2e_orchestration/architecture/11-risks-and-technical-debt.md`（仅 T09 文档面状态过期引用）
- `specs/t09-module-doc-contract-template-20260610/**`

禁止修改：

- `src/**`
- `tests/**`
- `scripts/**`
- `Makefile`
- `docs/repository-metadata/entrypoint-registry.md`

## 3. 验证

- `git diff --check`
- 检查 `git diff --name-only` 不包含源码、测试或脚本路径。
- 检查 T09 模块文档目录和 `_template` 文件存在。
- 检索 T09 缺口状态是否从当前盘点中移除或改为已补齐。
