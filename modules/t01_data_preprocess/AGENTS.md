# T01 Agent Guardrails

本文件只保留 `t01_data_preprocess` 的 Agent 局部红线；模块源事实以 `SPEC.md`、`INTERFACE_CONTRACT.md` 与 `architecture/*` 为准。

- 不回退 accepted baseline、active freeze baseline 或 continuation 契约，除非用户明确授权。
- 官方业务入口以 repo-level CLI 子命令和已登记脚本为准；不要把辅助脚本升级为模块契约。
- 性能优化不得通过改变 accepted 业务结果换取速度。
- 内网测试交付需要给出可直接执行的下拉、运行和关键信息回传命令。
- 不在模块根目录新增 `SKILL.md`。
