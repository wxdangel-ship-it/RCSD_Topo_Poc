# 03 上下文与范围

## 当前上下文
- T01 解决的是普通道路网络上的双向路段逐级提取问题。
- 它不是终局建模模块，而是后续关键路口锚定和更完整路段构建的前置基础模块。

## 当前范围
- working bootstrap
- roundabout preprocessing
- Step1：pair candidate 发现
- Step2：首轮 validated / trunk / segment_body / residual
- Step3：refresh
- Step4：residual graph 下一轮构段
- Step5A / Step5B / Step5C：staged residual graph 收尾
- 三样例活动基线冻结与 compare

## 当前范围外
- 封闭式道路场景
- 普通道路单向 Segment
- Step6
- 更完整的多轮闭环治理
- repo 级模块激活治理
