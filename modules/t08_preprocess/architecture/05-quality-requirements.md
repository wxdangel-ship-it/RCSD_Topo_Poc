# 05 质量要求

## 1. 通用质量

- 所有工具不原地修改输入。
- 输出文件名必须符合 `_toolX` 约束。
- 输入缺 CRS、必需字段缺失、几何不可用时必须显式失败或审计，不得静默继续。
- summary 必须记录输入、输出、参数、CRS、计数、失败原因和性能字段。
- Tool11 不解析 CRS 时，summary 必须明确记录 `copied_without_transformation`，并以文件哈希证明内容不变。

## 2. GIS 与拓扑要求

- Tool1/2/3/4/5/6/7/8/9 的输出 CRS 按 contract 固定或显式记录。
- Tool3 环岛聚合只对多 node 环岛组写 `kind_2=64`。
- Tool3 必须完整读取 Road 输入；缺失端点 Road 只允许在环岛拓扑计算中审计式跳过，不得删除 Road、补造 Node 或 silent fix。
- Tool4/5 修复必须保持语义组关系，不破坏 `mainnodeid`。
- Tool9 删除 RCSDNode 时按语义组整体判定，不能只按单 node 保留。
- Tool10 必须输出 `EPSG:3857 LineStringZ`，Z 原值不变；缺 Z、非有限 Z、非法 Point 或未知 CRS 均整批失败。切分形成的单点段必须显式审计后从线图层排除，不能 silent fix、跨断点拼接或复制成退化线。
- Tool11 不执行任何 CRS、几何或拓扑操作；SWSD/RCSD 全树和 FRCSD 白名单文件必须逐字节保持，源/主输出以及可选实验输出 SHA-256 不一致时整批失败。

## 3. 业务边界质量

- Tool6 只输出质检候选，不直接修复。
- Tool7/8 是 T09 证据，不是最终 restriction 结果。
- Tool4 只有在 Tool6 人工确认时才执行相应人工修复分支。
- Tool5 可复用 T02 历史修复逻辑，但输出仍属于 T08 copy-on-write 预处理成果。

## 4. 回归要求

测试应覆盖 Tool1 SHP / GeoJSON / FGB / GPKG 转换、输出命名和覆盖保护、Tool2 patch/kind/event road、Tool3 roundabout、缺失端点审计式跳过与 `closed_connect` alias 归一/冲突、Tool4 repair 与 Tool6 消费、Tool5 complex / one-to-many、Tool6 QC、Tool7 restriction、Tool8 arrow、Tool9 RCSD 清理、Tool10 PointZ 严格校验、排序/切段、Z/点数守恒、单点段显式审计排除、单 GPKG 落盘和覆盖保护，以及 Tool11 全量-only、FRCSD 白名单、可选实验子集、哈希、缺失项聚合和请求根覆盖保护。

## 5. 性能要求

大体量 FGB 输入必须流式读取；大体量 GPKG 读写优先使用直接 SQLite / 流式路径；Tool11 文件复制必须固定块流式处理，不把文件整体读入内存。性能优化不得省略 CRS/不变性、字段、summary 或 audit。工具脚本应提供进度输出，便于内网全量运行定位瓶颈。
