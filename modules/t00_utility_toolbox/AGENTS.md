# T00 - AGENTS

## 开工前先读

1. `../../AGENTS.md`
2. `../../docs/doc-governance/README.md`
3. `architecture/01-introduction-and-goals.md`
4. `architecture/03-context-and-scope.md`
5. `INTERFACE_CONTRACT.md`
6. `README.md`（仅在需要执行入口时）
7. `../../specs/t00-utility-toolbox/*`（仅在追溯治理过程时）

若这些文档冲突，先列冲突点并停止，不得自行选择有利口径继续扩写实现。

## 模块角色与边界

- 模块 ID：`t00_utility_toolbox`
- 模块名称：`T00 Utility Toolbox`
- 模块角色：纳入治理的项目内工具集合模块
- `T00` 不是 Skill
- `T00` 不是业务生产模块
- `T00` 不直接生成 RCSD 业务要素
- 当前正式收录范围为 `Tool1-Tool7`、`Tool9` 与 `Tool10`
- `Tool8` 当前未登记，不得因编号连续性自动推定在范围内

## 持续有效的工作规则

- 模块级长期事实以 `architecture/*` 与 `INTERFACE_CONTRACT.md` 为准。
- `README.md` 只承担操作者入口和固定脚本索引，不替代长期源事实。
- 官方入口以 repo root `scripts/` 和仓库入口注册表为准；不新增模块级私有入口。
- 新工具进入 `T00` 前，先补规格与契约，再进入实现。
- 若文档、脚本与实现口径冲突，先停下并汇报。

## 禁止事项

- 不得把 `T00` 演化成业务生产模块。
- 不得未经确认擅自扩展 `Tool1-Tool7`、`Tool9` 与 `Tool10` 的范围。
- 不得绕过 `spec` 与契约直接编码扩写。
- 不得引入复杂 manifest、数据库落仓或重型产线编排。
- 不得在模块根目录新增 `SKILL.md`。
