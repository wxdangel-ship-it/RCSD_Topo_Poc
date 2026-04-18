# t03_virtual_junction_anchor 执行约束

- 本模块当前正式承接“冻结 `Step3 legal-space baseline` 之上的 `Step4-7 clarified formal stage`”。
- `Step3` 是冻结前置层；禁止在 T03 中重新定义 `allowed space / corridor / 50m fallback`。
- 当前正式输入契约固定为 Anchor61 `case-package` 与对应 Step3 run root。
- 当前正式模板只包括 `center_junction / single_sided_t_mouth`。
- `Step45` 继续承担 `A / B / C` 分类与中间结果包职责；`Step67` 继续承担受约束几何与 `accepted / rejected` 发布职责。
- 禁止把 T02 独立 `diverge / merge` 语义、`cleanup / trim` 补救链或未冻结 solver 参数偷渡为当前正式契约。
- `Step67` 当前没有 repo 官方 CLI；不要顺手新增入口或修改 entrypoint registry。
- 模块级长期真相以 `INTERFACE_CONTRACT.md` 与 `architecture/*` 为准；`README.md` 只承担操作者入口职责。
- 若 T03 文档与 T02 正式契约冲突，必须以项目任务书 + `modules/t02_junction_anchor/*` 当前正式口径为准并显式回写。
