# 04 方案策略

本文件是 T06 的详细版需求 / 落地策略说明。它解释 T06 如何从 T01 SWSD Segment 与 T05 SWSD-RCSD relation 构建 RCSDSegment、判定 replaceable，并输出 F-RCSD Road / Node。稳定输入输出、入口和参数以 `INTERFACE_CONTRACT.md` 为准；旧结构文档 `02-business-rules.md`、`03-input-output-contract.md`、`04-algorithm-strategy.md` 作为兼容参考保留。

## 1. 总体策略

T06 采用三步链路：

1. Step1 从 T01 `segment.gpkg` 识别具备融合资格的 SWSD Segment。
2. Step2 用 T05 relation 和 copy-on-write RCSD 网络构建 buffer-based RCSDSegment，并输出最终 `replaceable` 集合。
3. Step3 只消费 Step2 replaceable，把对应 SWSD Segment 替换为 retained RCSDRoad / RCSDNode，输出 F-RCSD Road / Node。

模块的核心边界是“只替换已被 Step2 证明可替换的 Segment”。失败 Segment 可以输出诊断、候选修复证据和上游责任归因，但不得据此静默覆盖 T05 relation 或继续替换。

## 2. Step1：SWSD Segment 融合资格识别

### 2.1 业务目的

从 T01 Segment 中识别哪些 Segment 具备进入 RCSD 匹配和替换预检的基础条件。

### 2.2 输入与前提

- T01 `segment.gpkg`，依赖 `pair_nodes / junc_nodes / roads / sgrade` 等字段。
- SWSD `nodes.gpkg`，用于读取 `has_evd / is_anchor / kind_2`。

### 2.3 落地策略

- 对每个 Segment 解析 `pair_nodes + junc_nodes`，形成语义路口集合。
- `pair_nodes` 必须解析出两个不同的 SWSD 语义路口。
- `junc_nodes.kind_2 in {1,4096,8192}` 不参与 Step1 `has_evd / is_anchor` 判定，但仍保留为后续 optional junc 审计对象。
- eligibility 集合内所有语义路口 `has_evd=yes` 时进入候选集。
- 在候选集中，所有 eligibility 语义路口 `is_anchor in {yes, fail4_fallback}` 时进入 final fusion units。

### 2.4 输出与审计

- `t06_swsd_segment_candidates.*`
- `t06_swsd_segment_final_fusion_units.*`
- `t06_swsd_segment_rejected.*`
- `t06_step1_segment_stats.csv`
- `t06_step1_summary.json`

### 2.5 对错边界

- 对：`fail4_fallback` 视为可融合 anchor，豁免只作用于 junc eligibility 检查。
- 错：把 `junc_nodes` 当作 hard-stop，或把 `pair_nodes` 豁免掉。

## 3. Step2：Relation Mapping

### 3.1 业务目的

把 SWSD Segment 的 pair/junc 语义路口映射到 RCSD 语义路口，为 RCSDSegment 构建提供 required 与 optional 语义边界。

### 3.2 输入与前提

- Step1 final fusion units。
- T05 `intersection_match_all.geojson`。
- T05 `rcsdnode_out.gpkg`。

### 3.3 落地策略

- relation 只接受 `status=0` 且 `base_id>0`。
- `pair_nodes` 是 required semantic nodes，必须全部映射成功。
- 映射后 RCSD pair 两端归一到同一语义路口时，以 `rcsd_pair_nodes_not_distinct` 拒绝。
- `junc_nodes` 是 optional 内部通过 + 侧向阻断；映射成功进入 optional 审计，映射失败进入 dropped / lost attach 审计，不默认拖垮 pair-to-pair 主通道。
- RCSDNode 统一使用 `id / mainnodeid / subnodeid` 归一到 canonical semantic node key。

### 3.4 输出与审计

- relation mapping 审计字段写入 Step2 candidates / rejected / summary。

### 3.5 对错边界

- 对：pair relation 缺失是硬失败，junc relation 缺失是 optional 审计。
- 错：用失败 relation 或 `base_id=0` 建图。

## 4. Step2：Buffer-Based RCSDSegment 构建

### 4.1 业务目的

在 SWSD Segment 的空间范围内构建与 pair required semantic nodes 对应的 RCSD corridor，而不是简单拿 buffer 内全部连通分量。

### 4.2 输入与前提

- SWSD Segment 几何。
- `rcsdroad_out.gpkg / rcsdnode_out.gpkg`。
- pair required RCSD semantic nodes 和 optional junc seeds。

### 4.3 落地策略

- 使用 SWSD Segment 50m buffer 筛选 RCSDRoad / RCSDNode 候选。
- 构建 RCSD canonical semantic graph，避免 subnode 挂接导致同一语义路口被误判为断连。
- 在候选图中先识别 `formway & 128 != 0` 提前右转 road；只有满足二度链接保留或 required corridor 保留条件时才参与构建。
- 候选连通分量不能直接输出为 RCSDSegment，必须基于 pair required semantic nodes 构建最小 corridor 子图。
- 对额外 T05 mapped semantic nodes 与 optional junc 做 seed pruning：required corridor 内部保留为 `inner_nodes`，旁支或孤立挂接归为 `out_nodes` 并裁剪。
- 双向 Segment 需要保护 pair 两端正反向 directed corridor；单向 Segment 必须由 SWSDRoad directed graph 推导 source/target 后构建同向 RCSD corridor。

### 4.4 输出与审计

- `t06_rcsd_buffer_segments.*`
- `t06_rcsd_buffer_segment_rejected.*`
- `t06_rcsd_segment_candidates.*`
- `t06_rcsd_segment_rejected.*`

### 4.5 对错边界

- 对：retained graph 是 pair required semantic nodes 之间的最小可解释 corridor。
- 错：把 buffer 连通分量、pair 字段顺序或 `segmentid A_B` 顺序当作业务方向。

## 5. Step2：硬审计与 Replaceable 判定

### 5.1 业务目的

将 buffer 成功构建的候选压缩为真正可替换的 RCSDSegment。

### 5.2 落地策略

- retained graph 的叶子端点只能是 pair 对应 RCSD semantic nodes。
- retained graph 中不得存在 pair required corridor 内部解释节点以外的额外 mapped semantic nodes。
- `swsd_directionality=dual` 要求 RCSD pair 两端双向可达。
- `swsd_directionality=single` 要求按推导 source/target 存在同向 RCSD corridor。
- retained RCSDRoad 必须满足逐 road buffer overlap ratio；整体覆盖不一致比例和绝对长度不能超限。
- `kind_2=64 / 128` 的特殊路口按关联 Segment 组执行全组门控：关联 Segment 必须全部可替换，否则该组全部移出 replaceable。

### 5.3 输出与审计

- `t06_rcsd_segment_replaceable.*`
- `t06_special_junction_group_audit.*`
- `t06_step2_summary.json`

### 5.4 对错边界

- 对：`replaceable` 是经过全部硬审计与特殊组门控后的最终白名单。
- 错：把 candidates 当 replaceable，或特殊组部分通过就局部替换。

## 6. Step2 失败诊断与修复候选

### 6.1 业务目的

对失败 Segment 提供可解释诊断和人工复核材料，帮助定位上游 relation 或拓扑问题。

### 6.2 落地策略

- Step2 失败后执行 buffer-only probe，不依赖 T05 relation 绑定，只基于 SWSD Segment buffer 与 RCSD 图结构输出诊断。
- `t06_rcsd_repair_candidates.*` 可以记录原始 pair、候选 pair、错误 SWSD 端点、endpoint cluster、bridge road 和长度。
- repair candidate 只用于人工质检和问题定位，不驱动当前 Segment 自动替换。

### 6.3 输出与审计

- `t06_rcsd_buffer_only_probe.*`
- `t06_rcsd_repair_candidates.*`
- `t06_rcsd_segment_failure_business_audit.*`

### 6.4 对错边界

- 对：诊断材料指向可能的上游问题。
- 错：用 probe 或 repair candidate 覆盖 T05 relation 并继续生成 replaceable。

## 7. Step3：Segment Replacement

### 7.1 业务目的

把 Step2 replaceable SWSD Segment 替换为 RCSD 承载，并输出融合后的 F-RCSD Road / Node。

### 7.2 输入与前提

- Step2 `t06_rcsd_segment_replaceable.*`。
- T01 SWSD `segment / roads / nodes`。
- T05 Phase2 `rcsdroad_out / rcsdnode_out`。
- 可选 Step2 `t06_special_junction_group_audit.*` 中 passed 特殊组。

### 7.3 落地策略

- Step3 只消费 replaceable，不处理 rejected。
- 以 `swsd_segment_id` 建立替换单元，记录 SWSD `pair_nodes / junc_nodes / roads` 与 retained RCSD road/node。
- 删除被替换 SWSDRoad。
- SWSDNode 只删除被替换 SWSDRoad 的端点 Node，不删除整个 SWSD 语义路口组。
- 引入 Step2 retained RCSDRoad / RCSDNode；passed 特殊组内部 RCSDRoad / RCSDNode 作为组级补充加入。
- 所有 replaceable Segment 的 `pair_nodes + junc_nodes` 形成待重建语义路口集合 C。
- 若 C 原 main node 被删除，按原 main node、剩余 SWSD node 最小 id、加入 C 的 RCSD node 最小 id 的优先级重选 main node。
- C 内 Node 继承原 main node 的 `kind / grade / kind_2 / grade_2 / closed_con`。

### 7.4 输出与审计

- `t06_frcsd_road.*`
- `t06_frcsd_node.*`
- `t06_step3_unreplaced_rcsd_roads.*`
- id collision audit、删除 / 引入 / main node 重建审计。

### 7.5 对错边界

- 对：F-RCSD Road/Node 使用 `source=1` 表示 RCSD，`source=2` 表示 SWSD。
- 错：因 SWSD/RCSD 原始 id 冲突而重写 id；应保留原 id 并依赖 `source` 区分。

## 8. 证据包与本地 Case

- 文本证据包用于内外网回传 T06 运行审计结果，不登记为 repo 官方 CLI。
- 输入切片包用于按中心点和范围抽取局部 SWSD / RCSD / relation 数据，形成可复现本地测试用例。
- 解包 manifest 必须记录输入路径、文件大小、SHA256、参数、依赖完整性和 replay 脚本。
