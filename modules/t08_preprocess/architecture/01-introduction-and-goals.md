# 01 引言与目标

## 1. 文档定位

本文件说明 T08 的架构背景、目标和边界。模块需求以 `SPEC.md` 为准，稳定接口以 `INTERFACE_CONTRACT.md` 为准，Tool1-Tool10 的实现策略见 `03-solution-strategy.md`。

## 2. 模块定位

T08 是项目正式前置数据治理模块。它把原始 SWSD / RCSD / patch / restriction / Laneinfo 数据转换为下游可消费的规范输入，并把历史散落在 T01/T02/T04 中的部分预处理、质检和修复职责收敛为独立工具组。

T08 不属于 T10 v1 Case runner 的 callable 步骤，但内网全量总控入口可以把 T08 作为独立前置阶段串入。它的输出服务 T01 Segment 构建、T03/T04/T05 路口关系层、T06 替换和 T09 通行规则恢复。

## 3. 目标

- 完成基础矢量格式转换和统一 CRS 输出。
- 显性化 SWSD Road/Node 下游所需字段，如 `patch_id / kind / kind_2 / grade_2`。
- 对路口类型、复杂路口、错误一对多场景进行 copy-on-write 修复或质检候选输出。
- 将 restriction 与 Laneinfo arrow 转为显性几何证据。
- 清理 RCSDNode / RCSDRoad，保证下游 relation 与 Segment 替换输入可解释。
- 将 Patch 内分散的 PointZ 轨迹转换并聚合成可审计的 `EPSG:3857 LineStringZ`。

## 4. 非目标

- 不构建 T01 Segment。
- 不生成 T03/T04 虚拟路口面。
- 不发布 T05 relation 主表。
- 不执行 T06 Segment 替换。
- Tool6 不直接修复输入，只输出人工质检候选。
- 不原地修改输入文件。
- Tool10 不做轨迹平滑、抽稀、吸附、补点或下游道路门控。

## 5. 架构边界

T08 每个 Tool 都有模块 callable 和已登记脚本包装。脚本负责参数和运行组织，业务规则以模块实现与 `INTERFACE_CONTRACT.md` 为准。
