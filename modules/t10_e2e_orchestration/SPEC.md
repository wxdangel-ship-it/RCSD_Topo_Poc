# T10 模块规格：端到端业务流程编排与 Case 证据组织

## 1. 模块定位

T10 是端到端业务流程编排与 Case 级证据组织模块。它不定义 T01-T09 的算法规则，而是把外部输入、模块间 handoff、Case package、Case replay、反馈迭代、全量运行 manifest 和可视化审计索引组织成可追溯的端到端证据链。

项目级主链仍是：

```text
T08 -> T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09
```

T10 v1 Case runner 编排：

```text
T01 -> T07 Step1/2 -> T03 -> T04 -> T05 -> T06 -> T09
```

T08 是独立前置预处理、质检和修复模块，不由 T10 Case runner 调用；内网全量总控可把 T08 作为独立阶段串入全量链路。
T07 Step3 是 T07 模块保留的可选兼容 relation 补锚能力，不属于 T10 v1 Case runner 默认主链；全量总控只有在显式配置兼容 relation 输入时才运行该阶段。
T10 必须保持连续 nodes handoff：T07 Step2 nodes 进入 T03，T03 downstream nodes 进入 T04，T04 downstream nodes 作为 `final_swsd_nodes` 进入 T05 / T06 / T09。

## 2. 业务目标

- 以 SWSD 语义路口 ID 组织端到端 Case 证据包，支持本地复现和内外网协作。
- 以 SWSD SegmentID 组织 Segment 级证据包，支持从既有 T10/T06 端到端结果反查失败 Segment 证据，并生成每 Segment 一个的轻量本地 T10 用例。
- 将每个模块的输入、输出、日志、状态和耗时显式记录到文件级 handoff，避免下游根据目录猜测产物。
- 区分节点状态 handoff 与 relation handoff：SWSD 侧最终锚定状态来自 T04 downstream nodes，T05 只发布最终 relation 与 RCSD copy-on-write 成果。
- 支持 Case 级 replay，复现 `T01 -> T09` 的关键链路并输出每阶段状态。
- 输出 T06 数据漏斗，解释从 SWSD Segment 到 F-RCSD 替换结果的数量流转、拒绝原因和替换质量。
- 将 T06 problem registry 中可回流上游的问题整理为 T03/T04/T05/T07/T08/T06 可消费的反馈包。
- 输出 T06 目视检查索引，帮助人工快速定位 T01/T03/T04/T05/T06/T07 图层和拓扑审计材料。
- 为内网全量执行提供 manifest、summary、resume 和 finalize-existing 能力。

## 3. 当前范围

### 3.1 正式支持

- workflow plan、handoff audit 和 summary。
- 单 Case / 多 Case evidence package。
- 单 Segment / 多 Segment evidence package。
- `spatial_slice` 局部 GPKG 切片。
- 文本 bundle 自动分片与解包。
- Case runner 端到端 replay。
- Segment replay 中 T03/T04 合法无候选时的显式空 handoff。
- T06 funnel。
- T06 upstream feedback package。
- T06 visual check summary。
- feedback iteration regression guard。
- innernet full pipeline manifest / summary / resume / finalize-existing。

### 3.2 当前非目标

- 不改变 T01-T09 模块算法。
- Case runner 不调用 T08。
- 不把 T06 feedback 直接变成 Step3 替换白名单。
- 不创建未登记的新 CLI 或模块入口。
- 不把内网未执行操作表述为已执行。

## 4. 上下游关系

| 方向 | 模块 / 数据 | 关系 |
|---|---|---|
| 上游 | T08 / 原始外部输入 | 为 Case package 和全量链路提供准备好的外部输入。 |
| 上游 | T01-T09 | 提供可编排的脚本、callable 和正式输出。 |
| 下游 | 人工 Case 分析 | 消费 Case package、funnel、visual check、summary 和日志。 |
| 下游 | T03/T04/T05/T07/T08/T06 后续迭代 | 消费 T10 从 T06 problem registry 提炼出的上游反馈。 |

## 5. 输入

| 输入 | 用途 |
|---|---|
| 外部输入 slot | Case package 和 workflow plan 的基础数据来源。 |
| SWSD semantic junction id | CaseID，用于定位局部 Case 范围。 |
| SWSD SegmentID | Segment 级证据包主输入；打包后 CaseID 使用 `segment_<SegmentID>`，正式 Segment 身份记录在 `scope.swsd_segment_id`。 |
| selector evidence | 将问题审计映射回语义路口 Case。 |
| Case package | Case runner 的端到端 replay 输入。 |
| 既有 T10 run root | Segment package 反查 T01 Segment、T06 problem registry、replacement plan 和 relation 证据的来源。 |
| T06 problem registry / relation audit | 生成上游反馈包和 feedback iteration 输入。 |
| 既有 full pipeline run root | resume 或 finalize-existing 的恢复对象。 |

## 6. 输出

| 输出 | 用途 |
|---|---|
| `t10_workflow_plan / t10_handoff_audit / t10_summary` | 工作流规划和 handoff 可用性审计。 |
| `t10_case_evidence_manifest / summary` | Case 范围、输入、切片和选择状态。 |
| `t10_multi_segment_evidence_manifest / summary` | 多 Segment 证据包顶层清单、Segment 状态和 evidence 引用。 |
| `external_inputs/<slot>/<slot>_slice.gpkg` | Case replay 使用的局部外部输入。 |
| `t10_e2e_run_manifest / summary` | Case runner 顶层状态和完成口径。 |
| `cases/<case_id>/<stage>/*` | 每个 Case 每阶段的命令、日志、状态和输出。 |
| `t10_t06_funnel.*` | T06 Step1/2/3 数据漏斗。 |
| `t10_upstream_*` | T06/T05 问题回流包。 |
| `t10_t06_visual_check_summary.*` | T06 目视叠加图层索引和快速审计指标。 |
| `t10_innernet_full_pipeline_manifest / summary` | 内网全量总控运行状态和 handoff。 |

## 7. 关键业务步骤

| 步骤 | 业务说明 |
|---|---|
| Workflow planning | 检查外部输入和模块 handoff slot 是否存在、是否是文件、是否可被下游消费。 |
| Case packaging | 按 SWSD 语义路口和半径组织局部证据包，补齐道路端点节点依赖并保留完整道路几何。 |
| Segment packaging | 按 SWSD SegmentID 从既有 T10 run root 反查 T01/T06 证据，以 evidence dependency closure 组织局部证据包。 |
| Case replay | 从 Case package 启动 T01-T09 关键链路，每阶段显式记录输入输出和状态；Segment closure 内 T03/T04 合法无候选时登记空 handoff，保持后续链路可执行。 |
| T06 funnel | 聚合 T06 Step1/2/3 数量流转、拒绝原因、replacement plan 和 problem registry 状态。 |
| T06 feedback | 将可回流上游的问题拆成 Segment、relation、side-group endpoint 和 pair-anchor endpoint cluster 等反馈视图。 |
| Visual check | 索引 T01/T03/T04/T05/T06/T07 关键 GPKP 图层，辅助人工叠加检查 CRS、提右重复和端点缺失。 |
| Full pipeline | 内网全量串联 T08-T09，记录阶段级 manifest、summary 和最终完成态。 |

## 8. 什么是对

- T10 只编排和记录，不改写 T01-T09 的算法事实。
- 每个 handoff 都有明确文件路径、状态和日志。
- Case package 优先使用局部切片，manifest-only 时才回退源路径。
- Segment package 必须记录 `scope_type=swsd_segment`、`swsd_segment_id`、T10 run root、T01 Segment source 和匹配到的 T06 evidence rows。
- Segment replay 不用半径补上下文；T03/T04 合法无候选时只生成带 `segment_no_candidate_handoff=true` 的空 relation/surface handoff。
- T06 feedback 只作为上游迭代输入，不直接驱动 Step3 替换。
- 顶层 summary 能明确区分 `passed / failed / blocked / skipped`。

## 9. 什么是错

- 只传目录给下游，让下游猜测关键文件。
- 把失败阶段的部分输出提升为正式 handoff。
- 用普通 Case 或非无候选失败触发 Segment 空 handoff 兜底。
- 用 T10 feedback 绕过 T03/T04/T05/T06 的正式审计。
- 在 Case runner 内重写模块算法或补救数据。
- 将未实际执行的内网运行表述为已经完成。

## 10. 当前治理缺口

- 真实数据下的 feedback iteration 质量、全量审计口径和跨模块 handoff 稳定性仍需持续收敛。
- T06 visual check 当前是 audit-only 索引，后续可补充更系统的自动化拓扑质量评估，但不得替代模块正式审计。
