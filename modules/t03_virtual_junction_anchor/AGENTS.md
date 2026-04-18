# t03_virtual_junction_anchor 执行约束

- 本模块当前正式承接“冻结 `Step3 legal-space baseline` 之上的 `Step4-5` 联合阶段”。
- `Step3` 是冻结前置层；禁止在 `Step4-5` 中重新定义 `allowed space / corridor / 50m fallback`。
- 当前正式输入契约固定为 Anchor61 `case-package` 与对应 Step3 run root。
- 禁止把 `Step6/7`、T02 独立 `diverge / merge` 语义、`cleanup / trim` 或其它补救链偷渡进当前 `Step4-5`。
- 当前正式模板只包括 `center_junction / single_sided_t_mouth`。
- 模块级长期真相以 `INTERFACE_CONTRACT.md` 与 `architecture/*` 为准；`README.md` 只承担操作者入口职责。
- 若 T03 文档与 T02 正式契约冲突，必须以项目任务书 + `modules/t02_junction_anchor/*` 当前正式口径为准并显式回写。
