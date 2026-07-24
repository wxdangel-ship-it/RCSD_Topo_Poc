# P05-Scheme-A-Dataset-P0 启动研究

## 1. 已确认业务边界

- T01 只构建 SWSD Segment 业务骨架，不提供 RCSD 替换真值。
- T07 当前继续使用 `DriveZone-only`。
- T03/T04/T05 是分层中间监督，T06 Step3 Road/Node 是最终主目标。
- T11 candidate 不是真值，T10 pass 不是对象标签，T09 不决定 Road/Node。

## 2. 启动前只读证据

- M0 正式 run 包含 741 个 sample、51 个可用 RoadGraph Case、520 个 T01/T03/T04/T05/T06/T07 artifact；520/520 路径存在且 SHA-256 匹配。
- M2R supervision 正式 run 包含 11,856 个 task target，label integrity error=0、split group conflict=0。
- Scheme A baseline 包含 8,863 Segment，其中 `USE_RCSD=2,190`、`KEEP_SWSD=6,619`、`MIXED_CARRIER=14`、unsafe ADVANCE_RIGHT mask=40。
- truth-free PTO candidate 共 295,357 个候选，Road/Node/T05 pointer 在冻结 Oracle 上全量可达，truth input/derived candidate均为0。
- 启动前流式探针的 2,190/2,190 `USE_RCSD` 结果已由正式 callable 与 Run A/B 复核；同时确认可用 Segment Road、T06 final Road/Node 和联合 exact 均为 `100%`，49+2安全门、CRS、资源与确定性通过，现已成为正式完成结论。

## 3. 对历史 P2-P0 的重新解释

历史 P2-P0 的 `USE_RCSD retention=0.165753` 描述的是当时 Scheme-A-P1/P2 carrier bundle的联合安全保留能力，不等于原始训练 Case缺少正确RCSD数据，也不等于T01应提供RCSD候选。本阶段保留该历史指标，同时增加模块角色正确的truth-free proposal reachability指标，避免把SWSD fallback、RCSD proposal和整图安全执行混为同一个分母。
