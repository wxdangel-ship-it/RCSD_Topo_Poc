# 03 上下文与范围

## 当前上下文

- T02 位于 T01 之后。
- T01 负责整理双向 Segment 相关上游事实；T02 当前承担资料 gate、anchor recognition，以及 stage3 `virtual intersection anchoring`。
- T02 不是最终锚定模块终局形态；当前正式 baseline 闭环覆盖 stage1 / stage2 / stage3，但仍未进入最终唯一锚定决策闭环。

## 当前范围

- 读取 T01 `segment`
- 读取 T01 `nodes`
- 读取 `DriveZone`
- 读取 `RCSDIntersection`
- 解析 `pair_nodes / junc_nodes`
- 构造 junction group
- 判定 `nodes.has_evd`
- 判定 `nodes.is_anchor`
- 判定 `segment.has_evd`
- 输出 `summary`
- 输出 `audit / log`
- 处理单 `mainnodeid` 的 `roads / RCSDRoad / RCSDNode`
- 输出虚拟路口面、RC 关联、状态、批次汇总与文本证据包支撑产物

## 当前范围外

- 最终唯一锚定决策结果
- 正式产线级全量虚拟路口批处理
- 候选生成与候选打分
- 概率 / 置信度
- 误伤捞回
- T02 自行定义的环岛新业务规则
- T01 生命周期重分类
