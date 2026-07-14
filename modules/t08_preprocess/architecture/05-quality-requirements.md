# 05 质量要求

## 1. 通用质量

- 所有工具不原地修改输入。
- 输出文件名必须符合 `_toolX` 约束。
- 输入缺 CRS、必需字段缺失、几何不可用时必须显式失败或审计，不得静默继续。
- summary 必须记录输入、输出、参数、CRS、计数、失败原因和性能字段。

## 2. GIS 与拓扑要求

- Tool1/2/3/4/5/6/7/8/9 的输出 CRS 按 contract 固定或显式记录。
- Tool3 环岛聚合只对多 node 环岛组写 `kind_2=64`。
- Tool3 必须完整读取 Road 输入；缺失端点 Road 只允许在环岛拓扑计算中审计式跳过，不得删除 Road、补造 Node 或 silent fix。
- Tool4/5 修复必须保持语义组关系，不破坏 `mainnodeid`。
- Tool9 删除 RCSDNode 时按语义组整体判定，不能只按单 node 保留。

## 3. 业务边界质量

- Tool6 只输出质检候选，不直接修复。
- Tool7/8 是 T09 证据，不是最终 restriction 结果。
- Tool4 只有在 Tool6 人工确认时才执行相应人工修复分支。
- Tool5 可复用 T02 历史修复逻辑，但输出仍属于 T08 copy-on-write 预处理成果。

## 4. 回归要求

测试应覆盖 Tool1 输出命名和覆盖保护、Tool2 patch/kind/event road、Tool3 roundabout、缺失端点审计式跳过与 `closed_connect` alias 归一/冲突、Tool4 repair 与 Tool6 消费、Tool5 complex / one-to-many、Tool6 QC、Tool7 restriction、Tool8 arrow、Tool9 RCSD 清理。

## 5. 性能要求

大体量 GPKG 读写优先使用直接 SQLite / 流式路径；性能优化不得省略 CRS、字段、summary 或 audit。工具脚本应提供进度输出，便于内网全量运行定位瓶颈。
