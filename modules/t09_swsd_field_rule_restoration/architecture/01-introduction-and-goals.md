# 01 引言与目标

## 1. 文档定位

本文件说明 T09 的架构背景、目标和边界。模块需求以 `SPEC.md` 为准，稳定接口以 `INTERFACE_CONTRACT.md` 为准，Step1-Step3 实现策略见 `03-solution-strategy.md`。

## 2. 模块定位

T09 是当前主链中从融合拓扑走向通行能力恢复的正式模块。它基于 SWSD restriction、Laneinfo arrow、SWSD Road/Node、T01 Segment 与 T06 F-RCSD 承载关系，还原现场路口级通行规则，并把显式禁止通行规则投影为 F-RCSD `LinkID -> outLinkID` restriction。

## 3. 目标

- Step1 构建 SWSD Arm 和 Movement 候选。
- Step2 用 restriction、arrow 和 special carrier 还原 Movement 级现场规则。
- Step3 使用 T06 SWSD-FRCSD Segment relation 将显式禁止规则投影到 F-RCSD。
- 支持 retained SWSD seed carrier fallback，并以风险标记暴露。
- 输出 GPKG / CSV / JSON 与 summary，服务 T10 Case 证据和人工复核。

## 4. 非目标

- 不生成 F-RCSD `RoadNextRoad`。
- 不以 F-RCSD 独立 Arm 构建作为主策略。
- 不消费 F-RCSD Laneinfo 或轨迹通行证据。
- 不修改 T06、T08、SWSD 或 F-RCSD 输入。
- 不新增 repo 官方 CLI 或主 runner 脚本。

## 5. 架构边界

T09 主业务通过模块 callable 执行。`scripts/t09_export_step3_input_text_bundle_innernet.sh` 只用于 Step3 输入证据包导出和解包，不替代 T09 Step1/2/3 主业务 callable。
