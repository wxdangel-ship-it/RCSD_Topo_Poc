# 05 质量要求

## 1. 编排正确性

- T10 v1 Case runner 固定为 `T01 -> T07 Step1/2 -> T03 -> T04 -> T05 -> T06 -> T09`。
- T07 Step3 不得作为 T05 后默认必经阶段；只有显式提供兼容 relation 输入时，才允许作为独立兼容补锚阶段运行。
- Case runner 不调用 T08。
- Full pipeline 总控可把 T08 作为独立前置阶段串入。
- 下游 handoff 必须是显式文件路径，不能只传目录。
- 阶段失败后，后续正式 handoff 不得消费失败阶段的部分输出。

## 2. GIS 与拓扑要求

- Case spatial slice 必须补齐被选中道路的端点节点依赖，并保留完整道路几何。
- Segment spatial slice 必须以 T01 Segment 几何 bounds 外扩 `radius_m` 作为窗口，补齐被选中道路的端点节点依赖，并保留完整道路几何。
- 切片 summary 必须记录 CRS、bounds、输入/输出要素数和 invalid geometry。
- T06 visual check 只索引图层和快速指标，不修改几何。

## 3. 审计质量

- manifest、summary、logs 和 handoff audit 必须能定位每个阶段输入输出。
- T06 funnel、feedback 和 visual check 必须记录来源 run/case 路径。
- resume / finalize-existing 必须区分补写完成态和重新执行阶段。

## 4. 回归要求

测试应覆盖 Case package、Segment package、multi-case / multi-segment layout、text bundle 分片解包、Case runner 阶段状态、T06 funnel、visual check、feedback iteration regression guard、manifest stage order、resume 和 finalize-existing。

## 5. 性能要求

T10 应记录每个 Case、每个 Segment、每个阶段和 full pipeline 的耗时。Case / Segment package 默认使用 spatial slice，避免复制全量输入；`copy_full` 只作为 Case 入口兼容诊断模式。
