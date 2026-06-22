# T04 Agent Guardrails

本文件只保留 `t04_divmerge_virtual_polygon` 的 Agent 局部红线；模块源事实以 `SPEC.md`、`INTERFACE_CONTRACT.md` 与 `architecture/*` 为准。

- 当前正式范围为 `Step1-7`；未获任务授权不得跨轮扩展其它步骤。
- 不新增 repo 官方 CLI，也不要顺手修改 `entrypoint-registry.md` 发明新入口。
- 可参考 T02/T03 的实现经验，但不得直接 import、调用或硬拷贝 T02/T03 模块代码。
- Step4 review 图必须使用 `STEP4_OK / STEP4_REVIEW / STEP4_FAIL`，不得用最终发布态冒充阶段结论。
- 若 T04 与 T02/T03 契约冲突，先停下并回报差异。
