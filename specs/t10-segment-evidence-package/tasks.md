# T10 Segment 级证据包任务清单

## Specify

- [x] 明确输入以 `SegmentID` 为主，支持多 Segment。
- [x] 明确每个 Segment 独立形成轻量本地 T10 用例。
- [x] 明确打包依据来自既有 T10 端到端结果和 T06 证据。
- [x] 明确不改变旧 semantic junction CaseID 语义。

## Plan

- [x] 定义 Segment CaseID 和正式 Segment identity 字段。
- [x] 定义 Segment 证据闭包来源：T01 `segment.gpkg` 目标几何与 T06 matched evidence rows。
- [x] 定义 Segment 外部输入选择不暴露半径，改由 T01 Segment + T06 evidence dependency closure 决定。
- [x] 定义输出结构和 text bundle 复用策略。
- [x] 定义 QA 审计字段和 1885118 验证策略。

## Implement

- [x] 新增 Segment package builder。
- [x] 新增 Segment spatial slice 支持。
- [x] 新增正式脚本 `scripts/t10_pack_innernet_segments.sh`。
- [x] 更新 T10 模块导出。
- [x] 更新模块源事实、README、架构和入口 registry。

## Test

- [x] 覆盖 Segment 几何定位与 manifest scope。
- [x] 覆盖多 Segment 独立目录。
- [x] 覆盖 text bundle 解包结构。
- [x] 覆盖脚本语法。

## QA

- [x] CRS 与坐标变换记录在 manifest。
- [x] 拓扑不 silent fix，记录 invalid geometry。
- [x] 几何语义记录 Segment center / bounds / evidence dependency closure。
- [x] 审计可追溯到 T10 run root、T01 Segment 和 T06 evidence。
- [x] 性能可通过 feature count、file size 和 materialized count 观察。
- [x] 1885118 抽样验证结果已记录到 `verification-1885118.md`。
