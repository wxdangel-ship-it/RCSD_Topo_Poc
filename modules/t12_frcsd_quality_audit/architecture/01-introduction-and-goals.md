# 01 Introduction And Goals

## 上下文

1V1 FRCSD 由 1V1 匹配技术融合生成，不是 T06 Segment 替换结果。业务假设要求它在通行性上与 SWSD 等价，但质量检查必须先用数据验证该假设。

## 目标

- 以 SWSD 必需方向为质量要求，检查 1V1 FRCSD carrier。
- 用真实路口节点组和 portal 避免单节点锚定误报。
- 形成 canonical 候选、raw endpoint 自动决定、可选 QA 覆盖和正式问题的可追溯证据。

## 兼容边界

RCSDIntersection 是 T07/T10 标准输入和人工标准路口。T06 证据可辅助解释，但 T12 target 始终是显式原始 1V1 FRCSD。

## 非目标

- 不修复数据，不改变 T06/T09/T11，不从单用例推导生产强规则。
