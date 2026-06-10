# 10 质量要求

## 1. 可理解

- 模块职责与边界应从文档直接读出
- `README.md` 必须能让人快速理解模块业务目标、输入输出、关键步骤和对错边界
- `architecture/04-solution-strategy.md` 必须用中文说明每个业务步骤如何落地

## 2. 可运行

- 模块官方入口应稳定、可重复执行

## 3. 可诊断

- 成功与失败都应有可追溯产物

## 4. 可治理

- 文档、实现、Skill 和脚本边界清晰
- 稳定接口变化必须同步 `INTERFACE_CONTRACT.md`
- 业务步骤变化必须同步 `architecture/04-solution-strategy.md`
