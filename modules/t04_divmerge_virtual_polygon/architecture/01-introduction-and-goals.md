# 01 引言与目标

## 1. 文档定位

本文件说明 T04 的架构背景、目标和边界。模块需求以 `SPEC.md` 为准，稳定接口以 `INTERFACE_CONTRACT.md` 为准，Step1-Step7 实现策略见 `03-solution-strategy.md`。

## 2. 模块定位

T04 是项目路口 1:1 关系层中的复杂虚拟锚定模块。T07 处理已有路口面，T03 处理交叉 / T 型虚拟路口，T04 负责分歧、合流、连续分歧 / 合流和复杂 `kind_2=128` 场景。它输出的主价值不是单独的 `nodes.gpkg` 状态，而是受事实证据和道路面约束的 accepted surface 以及面向 T05 的 relation evidence。

## 3. 目标

- 以 Step1-Step7 处理复杂路口候选，形成 accepted / rejected 分层结果。
- 用 DivStripZone、DriveZone、RCSDRoad、RCSDNode 和 SWSD 拓扑解释事实事件，避免用抽象点伪造主证据。
- 将 road-surface fork、partial RCSD、road-only、SWSD-only 等弱证据场景转为可审计 fallback。
- 输出 T05 可消费的 surface、relation evidence、nodes 状态和 final 1:1 cardinality 审计。

## 4. 非目标

- 不处理 T03 负责的交叉 / T 型虚拟路口。
- 不把 rejected baseline 样本强行修成 accepted。
- 不把 `STEP4_REVIEW` 作为 Step7 最终状态。
- 不用 T06 Segment 阶段反推复杂路口基点。

## 5. 架构边界

T04 的业务主链由 `admission`、`local_context`、`topology`、`event_interpretation`、`support_domain`、`polygon_assembly`、`final_publish` 等模块承载；工程编排和批处理由 `batch_runner`、`internal_full_input_runner`、`full_input_*`、`nodes_publish`、`outputs` 等模块承载。架构文档只描述业务和设计边界，具体字段和值域以 `INTERFACE_CONTRACT.md` 为准。
