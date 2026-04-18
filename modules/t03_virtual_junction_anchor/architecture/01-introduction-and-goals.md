# 01 Introduction And Goals

## 目标

- 维护 T03 独立模块，承接冻结 `Step3 legal-space baseline` 之上的 `Step4-7 clarified formal stage`
- 以低结构债方式承载 Anchor61 `case-package` + Step3 baseline run root 的批量审查与最终发布能力
- 在不新增 repo 官方 `Step67` CLI 的前提下，保持 `Step45` 官方入口、`Step67` 正式交付与 closeout 口径一致

## 当前兼容

- 当前实现以 `Step3` 为冻结前置层
- `Step45` 继续承担前置分类与中间结果包职责
- `Step67` 继续承担受约束几何与最终 `accepted / rejected` 发布职责
- 视觉审计层继续保留 `V1-V5`，但不再等价于主机器状态

## 非目标

- 本轮不重新定义 `Step3`
- 本轮不把 `20m`、buffer、ratio 等 solver 参数冻结成长期业务契约
- 本轮不迁移 T02 的 cleanup/trim 补救链
- 本轮不新增 repo 官方 `Step67` CLI
