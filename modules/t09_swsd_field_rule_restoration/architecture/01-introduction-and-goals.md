# 01 Introduction And Goals

## 1. 模块目标

T09 的目标是把 SWSD 现场通行规则证据还原为可审计的路口级规则，并把显式禁止通行关系恢复到 F-RCSD 承载网络。

## 2. 业务目标

1. 基于 SWSD Node / Road 与 T01 Segment 构建语义路口 Arm 和 Arm-to-Arm Movement。
2. 基于 T08 Tool7 restriction 和 Tool8 arrow 还原现场禁止通行证据、箭头证据和冲突证据。
3. 基于 T06 SWSD-FRCSD Segment relation，把已确认 SWSD 禁止关系投影到 F-RCSD `LinkID -> outLinkID`。

## 3. 成功标准

- 读者可从 `README.md` 理解 T09 做什么、输入输出是什么、什么是对和错。
- 读者可从 `04-solution-strategy.md` 理解 Step1/2/3 每一步如何落地。
- AI 或审计者可从 `INTERFACE_CONTRACT.md` 确认稳定输入、输出、callable 和验收口径。

## 4. 当前非目标

- 不生成 F-RCSD `RoadNextRoad`。
- 不以 F-RCSD 独立 Arm 构建替代 T06 relation-first 策略。
- 不补充 RCSD Laneinfo 或轨迹证据。
- 不修改上游或输入数据。
