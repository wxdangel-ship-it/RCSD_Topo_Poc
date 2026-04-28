# 01 Introduction And Goals

## 目标

- 维护 T03 独立模块，以 `Step1~Step7` 表达当前正式业务主链
- 以低结构债方式承载 Anchor61 `case-package` / internal full-input 局部上下文、冻结合法空间、RCSD 关联、负向约束、受约束几何与最终发布能力
- 在不新增 repo 官方 finalization CLI 的前提下，保持历史命名入口、兼容输出文件名、正式交付与 closeout 口径一致

## 当前兼容

- 当前实现以 `Step3` 为冻结前置层，也是正式业务主链中的合法空间冻结步骤
- `Association` 作为 `Step4 + Step5` 的实现/输出标签
- `Finalization` 作为 `Step6 + Step7` 的实现/输出标签
- 视觉审计层继续保留 `V1-V5`，但不再等价于主机器状态

## 非目标

- 本轮不重新定义 `Step3`
- 本轮不把 `20m`、buffer、ratio 等 solver 参数冻结成长期业务契约
- 本轮不引入 cleanup/trim 补救链
- 本轮不新增 repo 官方 finalization CLI
