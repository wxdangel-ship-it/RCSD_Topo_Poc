# 03 Context And Scope

## 1. 上下文

T09 位于 T06 之后、T10 Case 证据组织之前。T06 生成 F-RCSD Road / Node 和 SWSD-FRCSD Segment relation，T09 基于这些承载关系恢复融合后路口的禁止通行关系。

```text
T08 Tool7 / Tool8 + T01 Segment + SWSD Node/Road
  -> T09 Step1/2 SWSD rule restoration
  -> T06 relation + F-RCSD Road/Node
  -> T09 Step3 F-RCSD restriction
```

## 2. 范围内

- SWSD 语义路口 Arm 构建。
- Arm-to-Arm Movement 候选构建。
- restriction、arrow、special carrier、topology not applicable 证据输出。
- SWSD restored field rules 输出。
- F-RCSD `frcsd_restriction.*` 输出。
- 输入、输出、跳过原因、CRS、性能和证据链 summary。

## 3. 范围外

- F-RCSD `RoadNextRoad` 生成。
- F-RCSD Laneinfo / 轨迹通行证据恢复。
- 对 T06 relation 的自动修复。
- 对 T08 Tool7 / Tool8 字段语义的重新定义。
- 对 SWSD / F-RCSD 输入文件的原地修改。
