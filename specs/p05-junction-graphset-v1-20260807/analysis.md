# 跨文档一致性分析

## 结论

新任务书与当前项目/P05 源事实一致，可以进入 implement 前置阶段；没有发现需要用户
重新裁决的业务冲突。

## 一致性矩阵

| 主题 | 当前源事实 | 本任务处理 |
|---|---|---|
| T01 | 冻结 Junction/Segment 等业务骨架 | 不修改、不训练 |
| T07 Step1 | DriveZone-only | 独立输入 view，RCSD 物理缺席 |
| 路口范围 | 优先替代 T07/T03/T04/T05 | 本轮唯一模型业务范围 |
| 虚拟面 | 不要求旧几何 exact；对象约束必须正确 | REQUIRED/FORBIDDEN/UNKNOWN |
| 锚定 | 模型内前置决定，后层不可反选 | state 先于 structured decode |
| 几何 | 模型选对象/位置，确定性层执行 | materializer 不作业务判断 |
| 旧策略 | 推理期退出 | 仅 label/evaluation |
| Segment/提右/Movement | 当前后置 | 全部排除 |
| 安全 | 正向决定与 ABSTAIN/fallback 分开 | 双 exact 与零危险门 |

## 未改内容

本启动提交只新增 SpecKit 文档；未修改源码、测试、项目或模块源事实、T01–T12、正式
接口、入口 registry、数据、模型 checkpoint 和训练工件。
