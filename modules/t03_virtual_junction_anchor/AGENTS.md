# t03_virtual_junction_anchor 执行约束

- 本模块当前正式业务主链按 `Step1~Step7` 表达：case 受理、模板归类、合法空间冻结、RCSD 关联识别、foreign / excluded 负向约束、受约束几何生成、最终验收发布。
- `Step3` 是正式业务步骤，也是冻结前置层；禁止在 T03 后续步骤中重新定义 `allowed space / corridor / 50m fallback`。
- 当前正式输入契约固定为 Anchor61 `case-package` / internal full-input 局部上下文与对应冻结前置结果。
- 当前正式模板只包括 `center_junction / single_sided_t_mouth`。
- `Association` 与 `Finalization` 只作为实现阶段、输出文件名前缀和代码符号保留；不要把它们重新写成正式需求主结构。
- 禁止把 T02 独立 `diverge / merge` 语义、`cleanup / trim` 补救链或未冻结 solver 参数偷渡为当前正式契约。
- 当前不新增、不删除、不重命名 repo 官方 CLI；历史 finalization wrapper 已退役，不再作为模块入口事实维护。
- 模块级长期真相以 `INTERFACE_CONTRACT.md` 与 `architecture/*` 为准；`README.md` 只承担操作者入口职责。
- 若 T03 文档与 T02 正式契约冲突，必须以项目任务书 + `modules/t02_junction_anchor/*` 当前正式口径为准并显式回写。
