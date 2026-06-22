# 02 数据与领域模型

## 1. 上下游数据关系

T10 消费外部输入、T01-T09 模块输出、T06 problem registry、T06 relation audit、Case package 和已有 full pipeline run root。T10 输出 workflow plan、handoff audit、Case evidence package、Case replay manifest、T06 funnel、feedback package、visual check summary 和 full pipeline manifest / summary。

## 2. 核心业务对象

| 对象 | 业务含义 |
|---|---|
| external input slot | Case package 和 workflow plan 的外部输入位置。 |
| handoff slot | 模块间正式文件级产物位置。 |
| CaseID | SWSD semantic junction id，不是坐标。 |
| Case package | 以 CaseID 和半径组织的局部外部输入证据包。 |
| spatial slice | `include_files=true` 时默认生成的局部 GPKG 输入切片。 |
| stage record | Case runner 或 full pipeline 中单阶段的输入、输出、日志和状态。 |
| T06 funnel | SWSD Segment 到 F-RCSD 替换结果的数量流转和拒绝原因视图。 |
| upstream feedback | 从 T06 problem registry / relation audit 提炼的上游迭代输入。 |
| visual check summary | T01/T03/T04/T05/T06/T07 关键图层索引和快速审计指标。 |
| full pipeline manifest | 内网全量执行的阶段顺序、输入输出和 execution context。 |

## 3. 关键状态语义

- `passed / failed / blocked / skipped` 是 T10 顶层完成口径，不替代模块内部质量结论。
- `manifest_only` 只声明 Case 范围，不物化矢量。
- `spatial_slice_completed` 表示 Case package 已生成局部切片。
- `T10_FEEDBACK_ITERATIONS=0` 是默认单轮模式；大于 0 时才执行 feedback iteration。
- `FINALIZE_EXISTING=1` 只补写既有 full pipeline run 的完成态，不重新执行模块算法。

## 4. 数据流

1. Workflow planning 检查外部输入和 handoff slot。
2. Case packaging 按 CaseID 和半径生成 manifest 或 spatial slice。
3. Case runner 从 package 启动 T01-T09 关键链路，并记录阶段级结果。
4. T06 funnel、visual check 和 feedback 从已产出的阶段结果中读取证据。
5. Innernet full pipeline 脚本串联全量阶段并写入 manifest / summary。

## 5. 领域边界

T10 的 feedback 是上游迭代输入，不是替换执行白名单。T10 的 visual check 是 audit-only 索引，不替代 T06 / T09 正式审计。
