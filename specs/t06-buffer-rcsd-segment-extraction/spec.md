# T06 Buffer-Based RCSD Segment Extraction Spec

## Product View

T06 阶段二需要从 SWSD Segment 出发，在 RCSD copy-on-write 网络中提取可审查的 RCSDSegment 子图。目标不是立即执行替换，而是生成更贴近业务走廊的 RCSD Segment 候选成果、失败原因和审计信息。

当前全局 pair-to-pair BFS 策略容易受 RCSD 全局拓扑断连、绕行路径和额外语义路口影响。新策略以 SWSD Segment 几何为局部走廊约束，先构建候选 RCSD 子图，再按 required semantic nodes 覆盖和裁剪规则生成 RCSDSegment。

## Architecture View

- Step1 保持不变，继续输出 `fusion_units` 与 `junc_kind2_exempt_nodes`。
- Step2 新增 buffer-based extraction path：
  - 基于 SWSD Segment geometry 构建 50m buffer。
  - RCSDRoad 使用 `intersects + 阈值` 进入候选集。
  - RCSDNode 使用 `within/covers` 进入候选集。
  - 构图前按 `formway` bit7 去除提前右转 road。
  - `required_semantic_nodes = pair_nodes relation + 非豁免 junc_nodes relation`。
  - `junc_kind2_exempt_nodes` 不作为 required，可作为 optional allowed 审计。
  - 在候选无向图中查找覆盖全部 required semantic nodes 的连通分量。
  - 对覆盖分量执行 seed-based out/inner 裁剪，输出 RCSDSegment 候选成果与审计。
- 保留现有 Step2 pair-to-pair path 代码，直到新策略经内网审查确认可替代。

## Development View

新增实现应限定在 `t06_segment_fusion_precheck` 模块内，不新增 repo CLI、scripts、Makefile 或模块 `run.py`。优先新增独立 helper 模块，避免继续扩大既有 orchestration 文件。

主要新增能力：

- 空间候选选择。
- 提前右转识别和排除。
- 无向候选图构建与连通分量分析。
- required / optional semantic node 分类。
- seed group BFS 裁剪。
- RCSDSegment 审查输出字段与 summary 计数。

## Testing View

单元测试必须覆盖：

- `formway` bit7 识别提前右转，含组合 bit。
- RCSDRoad `intersects + 阈值` 候选筛选，避免 `within` 漏边。
- `junc_kind2_exempt_nodes` 不作为 required semantic nodes。
- 连通分量缺 required node 时失败。
- 额外语义路口连接 required 两端时进入 `inner_nodes`。
- 额外语义路口连向孤立挂接或外部语义路口时进入 `out_nodes` 并被裁剪。
- 输出审计字段可定位 retained / excluded road ids。

## QA View

QA 审查重点：

- CRS 全部归一到处理 CRS，不静默猜测。
- 候选筛选、提前右转排除、连通分量与裁剪结果均可追溯。
- 不对输入 `segment.gpkg / nodes.gpkg / rcsdroad_out.gpkg / rcsdnode_out.gpkg / intersection_match_all.geojson` 原地写入。
- 输出失败原因必须区分空间候选为空、required relation 缺失、候选分量不覆盖 required、提前右转排除导致断连、裁剪后为空等情形。
- 第一版以内网样本人工审查为准，不把 replaceable 计数提升作为唯一成功标准。

## Confirmed Business Rules

- RCSDRoad 空间筛选采用 `intersects + 阈值`，不采用纯 `within`。
- 提前右转使用 `formway` bit 运算识别：bit7 = `128`。
- `junc_kind2_exempt_nodes` 不作为 required semantic nodes。
- `pair_nodes` 不适用 kind_2 豁免。
- `junc_kind2_exempt_nodes` 若存在 relation，可作为 optional allowed semantic nodes 审计保留。
