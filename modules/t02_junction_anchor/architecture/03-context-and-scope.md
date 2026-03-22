# 03 上下文与范围

## 当前上下文

- T02 位于 T01 之后。
- T01 负责整理双向 Segment 相关上游事实；T02 当前只承担“这些相关路口是否有有效资料”的 gate 判断。
- T02 不是最终锚定模块终局形态；当前只是为后续 anchoring 提供前置门禁与审计基础。

## 当前范围

- 读取 T01 `segment`
- 读取 T01 `nodes`
- 读取 `DriveZone`
- 解析 `pair_nodes / junc_nodes`
- 构造 junction group
- 判定 `nodes.has_evd`
- 判定 `segment.has_evd`
- 输出 `summary`
- 输出 `audit / log`

## 当前范围外

- 最终锚定结果
- 候选生成与候选打分
- 概率 / 置信度
- 误伤捞回
- T02 自行定义的环岛新业务规则
- T01 生命周期重分类
