# T06 RCSD Road—Segment 唯一分配实施计划

**Branch**: `codex/p02-wuhan-local-experiment-20260714` | **Date**: 2026-07-14

## 1. 摘要

在不修改 T01/T05 与人工锚定的前提下，为 T06 Step3 增加所有权后统一收口：普通 Road 发布唯一 Segment，特殊路口内部与 connectivity Road 发布空 Segment owner；同步 relation、F-RCSD provenance、审计、summary 和正式契约。

## 2. 宪章与治理检查

- 源事实冲突已由用户授权修订；通过。
- 变更影响 T06 正式业务口径，已建立 SpecKit 的产品/架构/研发/测试/QA 五视角；通过。
- 当前位于隔离分支，不在 `main`；通过。
- 不新增或改变入口；通过。
- 所有待改 `.py` 与测试写入前已检查字节数，均低于 100KB；通过。
- GIS 的 CRS、拓扑、几何、审计与性能均纳入验证；通过。

## 3. 技术方案

1. 扩展 ownership ledger：新增 `special_junction_internal` 与 `special_junction_ids`。
2. ownership 决策优先消费 Step2 `special_junction_group_internal` 正式 plan，避免几何末级规则把路口内部 Road 误分给普通 Segment。
3. 新增统一 assignment reconciliation：由 ownership `final_road_ids` 重写最终 Road 的 `t06_swsd_segment_ids` 和 added-road Segment 列表。
4. relation 收口：只保留当前 Segment owner 的 RCSD Road；特殊内部与 connectivity 使用独立 related 字段。
5. surface refresh 读取正式 replacement plan，重建特殊路口上下文并复用相同收口。
6. summary 增加单 owner/无 owner/多 owner 计数和多 owner 硬门禁。

## 4. 验证顺序

1. 聚焦 ownership 单元测试。
2. T06 相关 relation/construction/topology 测试。
3. T06 模块完整回归。
4. 使用 run08 完整输入重跑 T06 为 run09。
5. 逐条核对 8 条 Road、全部最终 Road 多值计数、Segment 方向拓扑、CRS、几何未改、审计与性能。

## 5. 风险与控制

- group member 裁剪后失去独立通路：由 relation/construction/topology 审计阻断，不恢复多归属。
- split Road 未继承 owner：使用 ownership `final_road_ids` 映射并增加测试。
- 特殊内部 Road 被 connectivity 抢占：特殊路口正式 plan 的语义优先级高于 connectivity 与几何。
- surface 后字段回退：surface ownership refresh 复用相同 reconciliation。
- 既有 P02 未提交改动冲突：只修改当前任务直接涉及的 T06 文件，逐文件复核 diff。
