# 007 - Roundabout Preprocess Integration

## 1. 为什么新增环岛预处理
- working Nodes / Roads 已经前移到模块开始阶段。
- 下一步需要把某些“路口级语义”提前在 Step1 之前固化。
- 环岛是第一类正式接入的路口级预处理对象：
  - 它不能继续作为一组松散 node 参与后续轮次
  - 需要先聚成单一语义路口，再参与 Step1-Step5

## 2. 当前 accepted 业务语义
- 环岛 road 识别：
  - `roadtype` 含 `bit3 = 8`
- 聚合方式：
  - 仅按共享 node 的拓扑连通关系
- 每组最小 node id 作为 mainnode
- 字段改写：
  - mainnode：`grade_2 = 1`, `kind_2 = 64`
  - member node：`grade_2 = 0`, `kind_2 = 0`
  - 全组 `mainnodeid = mainnode`
- 后续 Step1-Step5 中，凡属“全通路口”的输入位置，环岛 mainnode 与交叉路口同等处理

## 3. 环岛 mainnode 保护
- 环岛 mainnode 是受保护语义路口。
- 后续 generic node refresh 不允许覆盖 `1 / 64`。
- 也就是说：
  - 不允许降级成 `-1 / 1`
  - 不允许改写成 `3 / 1`
  - 不允许改写成 `3 / 2048`

## 4. 本轮未纳入的环岛扩展内容
- 环岛专属 trunk 特判
- 环岛专属 segment 收敛规则
- 环岛独立输出 schema 扩展
- 环岛与其他特殊路口的更复杂语义归并

## 5. 回归约束
- 环岛能力接入后，必须保持 XXXS freeze baseline 不回退。
- 若环岛能力在 XXXS 上引起差异：
  - 不能擅自更新 freeze
  - 必须先报告差异并等待用户确认
