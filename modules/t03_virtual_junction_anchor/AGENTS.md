# T03 Agent Guardrails

本文件只保留 `t03_virtual_junction_anchor` 的 Agent 局部红线；模块源事实以 `SPEC.md`、`INTERFACE_CONTRACT.md` 与 `architecture/*` 为准。

- 正式业务主链按 `Step1~Step7` 表达。
- `Step3` 是冻结前置层；T03 后续步骤不得重写 `allowed space / corridor / 50m fallback`。
- 正式模板只包括 `center_junction / single_sided_t_mouth`。
- `Association / Finalization` 只作为历史实现、输出前缀、代码符号和兼容说明，不得重新成为正式需求主结构。
- 不新增、不删除、不重命名 repo 官方 CLI；历史 finalization wrapper 不作为当前入口事实维护。
