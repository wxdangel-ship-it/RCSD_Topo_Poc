# 03 Context And Scope

## 上下文

- T03 继承 T02 的正式业务契约，而不是其既有结构债
- `Step3` 仍以中文冻结规则、allowed space、negative mask、`step3_state` 作为冻结前置层
- T03 当前只对 `kind_2 in {4, 2048}` 建立正式 `Step1~Step7` 业务主链

## 当前范围

- case loader
- Step1 最小上下文
- Step2 模板归类
- 冻结 Step3 prerequisite 读取
- Step4 RCSD 关联语义识别
- Step5 foreign / excluded 分类与审计
- Step6 受约束几何建立与后处理
- Step7 最终 `accepted / rejected` 发布
- 批量运行与审查产物

## 当前范围外

- `stage4` 连续链与 `complex 128`
- 新的 repo 官方 finalization CLI
- solver 常量、buffer 宽度、cover ratio 的长期冻结

## 说明

- `Step4~Step7` 的前提是：`Step3` 已冻结 allowed space，不得重新定义 branch trace / opposite guard / 50m fallback
- `foreign / opposite` 的判定不得覆盖当前语义路口关联 road 与其二度衔接 road
- `degree = 2` connector node 本身不进入 semantic core，但其串接的 candidate `RCSDRoad` 必须先按 chain 合并，再进入 `required / support / excluded`
- `single_sided_t_mouth` 的方向与 bridge / through-node 解释必须沿用冻结 Step3
- `V1-V5` 属于视觉审计层，不替代 `Step7 accepted / rejected`
