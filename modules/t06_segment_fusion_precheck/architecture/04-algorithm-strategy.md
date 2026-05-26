# 04 Algorithm Strategy

## 分层

- `parsing.py`：字段解析与 ID 规范化。
- `io.py`：vector/table 读写、run root 与三格式输出。
- `schemas.py`：稳定字段、失败原因与 artifacts dataclass。
- `step1_identify_fusion_units.py`：Step1 eligibility。
- `relation_mapping.py`：T05 relation loader 与 pair/junc mapping 校验。
- `graph_builders.py`：RCSD semantic node canonicalizer 与 buffer graph edge dataclass。
- `step2_extract_rcsd_segments.py`：Step2 orchestration。
- `buffer_segment_extraction.py`：Step2 buffer-based RCSDSegment 候选子图、提前右转排除、连通分量覆盖与裁剪。
- `runner.py`：组合 runner。
- `text_bundle.py`：非官方文本证据包压缩 / 解压 helper，复用内网运行脚本的输入参数形状，记录输入文件大小 / SHA256、运行参数、summary 与可复跑命令；同时支持中心点 + profile/radius 的输入切片包。

## 策略

- Step1 先解析 `pair_nodes / junc_nodes / roads`，再做 node eligibility。
- Step2 先 relation mapping，再使用 buffer-based 策略构建唯一 RCSD Segment 审查成果。
- buffer candidate graph 使用 RCSD semantic canonical key，避免 RCSDRoad 挂在 subnode 上时把同一语义路口误判为断连。
- required semantic nodes 必须落在同一候选连通分量内；不满足时输出 buffer rejected。
- 裁剪后保留 required semantic nodes、optional allowed nodes 与 inner nodes 间的连通 RCSDRoad，作为正式 RCSDSegment。
- 裁剪后的 retained graph 必须只以 pair 对应 RCSD semantic nodes 为叶子端点；junc 或其它节点成为叶子端点时输出 buffer rejected。
- `t06_rcsd_segment_candidates / replaceable` 是兼容输出，由同一 buffer 成功结果派生；不再执行 pair-to-pair BFS、方向一致性、主轴 / 粗长度趋势或唯一性筛选。
