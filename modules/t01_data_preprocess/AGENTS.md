# T01 - AGENTS

## 开工前先读

1. `../../AGENTS.md`
2. `../../docs/doc-governance/README.md`
3. `architecture/overview.md`
4. `architecture/06-accepted-baseline.md`
5. `INTERFACE_CONTRACT.md`
6. `README.md`（仅在需要执行入口时）
7. `history/*`（仅在追溯演进原因时）

若这些文档冲突，先列冲突点并停止，不得自行选择有利口径继续修改。

## 持续有效的工作规则

- 模块级长期事实以 `architecture/*` 与 `INTERFACE_CONTRACT.md` 为准。
- `README.md` 只承担操作者入口、运行说明与索引，不替代 accepted baseline。
- 官方业务入口以 repo-level CLI 子命令为准；repo root `scripts/t01_*.sh` 只是交付或环境辅助脚本，不替代模块契约。
- 未经用户明确确认，不得回退 accepted baseline、active freeze baseline 或 continuation 契约。
- 改文档前后必须对照 repo root `AGENTS.md`、`SPEC.md` 与 `src/rcsd_topo_poc/cli.py`，确认入口名、输出名和参数类别一致。
- 模块根目录不放 `SKILL.md`；标准可复用流程统一收口到 repo root `.agents/skills/`。

## Freeze Baseline Guardrails

- 当前 active freeze baseline：`modules/t01_data_preprocess/baselines/t01_skill_active_eight_sample_suite/`
- 未经用户明确认可，不得更新 freeze baseline。
- 任何性能优化不得通过改变 accepted 业务结果换取速度。

## 内网测试交付规则

- 进入内网测试阶段时，默认交付三件套：
  1. 当前 GitHub 版本内网下拉命令
  2. 可直接执行的内网运行脚本
  3. 可直接执行的关键信息回传命令
- 若用户已提供足够路径与版本信息，这三件套必须可直接执行，不得要求用户手工再替换参数。
