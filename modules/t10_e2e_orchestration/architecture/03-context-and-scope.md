# 03 Context And Scope

## 1. 上下文

项目当前主业务链为：

```text
T08 -> T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09
```

T10 v1 局部编排链路为：

```text
T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09
```

两者不冲突：T08 仍是主业务链前置质量模块，但 T10 v1 不直接调度 T08。

## 2. 外部输入范围

T10 v1 Case 证据包的外部输入包括：

- prepared SWSD nodes / roads
- DriveZone
- DivStripZone
- RCSDIntersection
- RCSDRoad
- RCSDNode
- T08 Tool7 restriction output
- T08 Tool8 lane-arrow output

## 3. 中间产物范围

T01 / T07 / T03 / T04 / T05 / T06 / T09 的中间产物只作为 handoff audit，不进入 v1 Case 外部输入证据包。

## 4. Candidate Suggest Scope

T10 `suggest` 可读取 T08/T05/T06/T09 等审计文件作为 selector evidence。selector evidence 只用于确定“哪些 SWSD 语义路口值得打包分析”，不进入最终 Case package payload。

候选 Case 的主键始终是 SWSD 语义路口 ID。若 selector evidence 只能提供 node id，T10 先用 SWSD nodes inventory 找到该 node 所属语义路口，再输出对应 CaseID。
