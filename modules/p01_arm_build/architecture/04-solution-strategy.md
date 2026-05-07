# 04 方案策略

## 总体策略

P01-A 按“输入读取 -> 语义路口 -> seed -> trace -> arm 聚合 -> 输出审计 -> 目视审查”的顺序实现。所有构建规则优先基于拓扑字段，不通过几何形态推导业务语义。

## 数据读取

使用 Fiona 读取矢量数据，统一字段大小写后构建轻量 Node / Road 模型。CRS、feature count、字段缺失情况写入 preflight。

## 语义路口

有效 `mainnodeid` 聚合为语义路口；无有效 `mainnodeid` 时按 Node 自身成组。internal road 是两端都落在当前 member node 集合内的 Road。

## Seed 和 Right-Turn

一端在当前路口、一端在外部的 Road 是 seed 候选。若 runner 通过 `--right-turn-formway-value` 显式传入已确认字段值，且 Road 的 `formway` 命中该值，则排除并审计；字段缺失或未声明确认值时只写 issue，不做几何反推。

## Trace

trace 从 seed 外侧端点继续。每步只沿拓扑连接向外追溯：

- degree 2 语义节点组可输出 `simple_through` 并继续。
- degree 0/1 输出 `dead_end`。
- degree >= 3 输出 `semantic_boundary`；如果 T 型主侧向无法稳定确认，则输出 `ambiguous_boundary` 与 `t_junction_uncertain`，不静默 through。
- 回到当前路口输出 `loop_to_current_junction`。
- 找不到下一条可用 Road 输出 `patch_boundary`。

## Arm 聚合

按 trace 的终端类型与终端语义路口 ID 聚合 InitialArm。当前 FinalArm 复制 InitialArm 并写入合并占位字段。

## 局部趋势候选

为辅助识别 trace 在 T 型或 ambiguous boundary 前被过度切碎的 case，模块额外输出 `LocalArmCandidate`。该候选只基于当前语义路口 seed road 从 member node 指向外侧 node 的局部趋势，把同侧进入 / 退出 / 双向 seed 归为参考分组，并可保留少量方向一致的外侧 stub road 作为目视证据。它不使用目标 case ID，不进入 FinalArm 合并规则。

## 输出与 QA

JSON 输出承担机器审计，GPKG 输出承担 GIS 审查，PNG 输出承担快速目视判断。summary 与 review index 承担批量筛查和人工优先级排序。
