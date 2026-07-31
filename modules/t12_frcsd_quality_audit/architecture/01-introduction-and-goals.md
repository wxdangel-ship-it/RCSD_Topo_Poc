# 01 Introduction And Goals

## 上下文

1V1 FRCSD 由 1V1 匹配技术融合生成，不是 T06 Segment 替换结果。业务假设要求它在通行性上与 SWSD 等价，但质量检查必须先用数据验证该假设。

## 目标

- 以 SWSD 方向要求为质量基准，既检查 1V1 FRCSD 是否缺少必需 carrier，也检查单向 Segment 是否在明确双端路口锚点之间出现唯一归属于当前 Segment 的非预期反向 carrier。
- 以正式 T03 rejected 为候选、原始 1V1 FRCSD 为复核 target，准确率优先发布路口所需拓扑缺失与现实变化/精度差异；以 T07 Step3 稳定 1:N/N:1 失败直接发布关系基数问题。
- 用真实路口节点组和 portal 避免单节点锚定误报。
- 形成 Segment LineString 与 Junction Point 两套独立的候选、自动决定、可选 QA 覆盖边界和正式问题证据。

## 兼容边界

RCSDIntersection 是 T07/T10 标准输入和人工标准路口。T06 证据可辅助解释，但 T12 target 始终是显式原始 1V1 FRCSD。T03/T07 只提供正式 Junction 来源，不改变 T03/T07 算法或回写其结果。

## 非目标

- 不修复数据，不改变 T03/T07/T06/T09/T11，不从单用例推导生产强规则。
