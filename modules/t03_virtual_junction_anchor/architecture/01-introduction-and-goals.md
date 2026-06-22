# 01 Introduction And Goals

## 上下文

T03 是项目“路口 1:1 关系层”的常规虚拟锚定模块。它承接 T07 已有路口面锚定之后仍未建立关系的常规交叉 / T 型路口，通过冻结合法活动空间、解释 RCSD 关联、生成受约束虚拟路口面和发布 relation evidence，支撑下游 T05 统一形成路口 1:1 关系成果。

T03 当前只描述自身正式业务链，不接管 T04 的分歧、合流、连续复杂路口，也不直接执行 T06 Segment 替换。

## 目标

- 维护 T03 独立模块，以 `Step1~Step7` 表达当前正式业务主链
- 以低结构债方式承载 Anchor61 `case-package` / internal full-input 局部上下文、冻结合法空间、RCSD 关联、负向约束、受约束几何与最终发布能力
- 在不新增 repo 官方 finalization CLI 的前提下，保持历史命名入口、兼容输出文件名、正式交付与 closeout 口径一致
- 将常规路口压缩为可审计、可回放、可交给 T05 消费的 SWSD-RCSD 关系证据

## 当前范围

- case loader 与 internal full-input candidate discovery
- Step1 当前 case 受理与局部上下文
- Step2 模板归类
- 冻结 Step3 prerequisite 读取与合法活动空间消费
- Step4 RCSD 关联语义识别
- Step5 foreign / excluded 分类与审计
- Step6 受约束几何建立与后处理
- Step7 最终 `accepted / rejected` 发布
- 批量运行、审计、review-only 产物和 T05 relation evidence handoff

## 兼容边界

- 当前实现以 `Step3` 为冻结前置层，也是正式业务主链中的合法空间冻结步骤
- `Association` 作为 `Step4 + Step5` 的实现/输出标签
- `Finalization` 作为 `Step6 + Step7` 的实现/输出标签
- 视觉审计层继续保留 `V1-V5`，但不再等价于主机器状态

## 非目标

- 本轮不重新定义 `Step3`
- 本轮不把 `20m`、buffer、ratio 等 solver 参数冻结成长期业务契约
- 本轮不引入 cleanup/trim 补救链
- 本轮不新增 repo 官方 finalization CLI
- 不处理 `stage4` 连续链、`complex 128`、环岛或 T04 负责的分歧 / 合流对象
