# T01 数据预处理模块

## 1. 当前阶段

- 当前模块阶段：`Step1 Pair Candidate + Step2 Segment POC`
- 当前定位：可运行、可审查、可解释的原型研发
- 当前不是：
  - 最终生产规则封板
  - 多轮闭环实现
  - 单向 Segment 终局实现

## 2. 当前能力

### 2.1 Step1

- 基于 seed / terminate 规则筛选语义路口
- 在语义路口图上执行 BFS 搜索
- 支持 through 节点继续追溯
- 支持双向确认
- 输出的是 `pair_candidates`

### 2.2 Step2

- 对 `pair_candidates` 做 validation
- 生成 candidate channel
- 回溯裁掉通往其他 terminate node 的分支
- 识别 trunk
- 构建 segment
- 输出 `validated_pairs` / `rejected_pair_candidates` / `trunk_roads` / `segment_roads`

## 3. 当前运行入口

### 3.1 Step1

```bash
python -m rcsd_topo_poc t01-step1-pair-poc \
  --road-path <road.shp|geojson> \
  --node-path <node.shp|geojson> \
  --strategy-config <strategy.json> \
  --out-root <out_root>
```

### 3.2 Step2

```bash
python -m rcsd_topo_poc t01-step2-segment-poc \
  --road-path <road.shp|geojson> \
  --node-path <node.shp|geojson> \
  --strategy-config <strategy.json> \
  --formway-mode strict \
  --out-root <out_root>
```

## 4. 当前主要产物

### 4.1 Step1 candidate 审查产物

- `pair_candidates.csv`
- `pair_links_candidates.geojson`
- `pair_candidate_nodes.geojson`
- `pair_support_roads.geojson`
- `pair_summary.json`
- `rule_audit.json`
- `search_audit.json`

### 4.2 Step2 validated / rejected 审查产物

- `validated_pairs.csv`
- `rejected_pair_candidates.csv`
- `pair_links_validated.geojson`
- `trunk_roads.geojson`
- `segment_roads.geojson`
- `branch_cut_roads.geojson`
- `pair_candidate_channel.geojson`
- `pair_validation_table.csv`
- `segment_summary.json`
- `working_graph_debug.geojson`

## 5. QGIS 审查建议

当前推荐同时打开：

- 原始 `roads.geojson` / `nodes.geojson`
- `pair_links_candidates.geojson`
- `pair_links_validated.geojson`
- `trunk_roads.geojson`
- `segment_roads.geojson`
- `branch_cut_roads.geojson`

这样可以直接对比：

- Step1 候选关系
- Step2 最终通过关系
- trunk 与 segment 的差异
- 被裁掉的分支

## 6. 当前已知限制

- trunk 归属冲突当前仍按保守 reject 处理
- `formway bit8` 只做可配置原型规则，不代表生产数据质量已确认
- 多轮工作图剥离语义当前只预留，不做完整实现
