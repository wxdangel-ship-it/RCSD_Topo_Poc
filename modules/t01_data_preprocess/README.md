# T01 数据预处理模块

## 当前状态
- 当前阶段：`Step5A/Step5B staged residual graph segment construction`
- 当前定位：
  - Step1：只发现 `pair_candidates`
  - Step2：对 candidate 做 `validated / rejected`，并输出 `trunk / segment_body / step3_residual`
  - Step4：基于上一轮 refreshed `Node / Road` 做 residual graph 构建
  - Step5：在 Step4 refreshed 基础上拆成 `Step5A / Step5B` 两阶段构建，并统一刷新 `Node / Road`
- 当前限制：
  - 仍属于 POC / 原型收敛
  - `Step6` 尚未启动

## 当前能力

### Step5A
- 读取 Step4 refreshed `nodes.geojson / roads.geojson`
- 剔除历史已有非空 `segmentid` 的 road
- 优先处理：
  - `grade_2 in {1,2}` 的交叉 / T 型路口
  - `grade_2 = 3, kind_2 = 4` 的交叉路口

### Step5B
- 基于 Step5A residual graph
- 再剔除 Step5A 新 `segment_body` road
- 在 residual graph 上对所有剩余双向路口做收尾构段

### Step5 merged / refreshed
- 合并 Step5A / Step5B validated pair 与 segment 结果
- 统一刷新：
  - Node：`grade_2 / kind_2`
  - Road：`s_grade / segmentid`

## 运行入口

### Step4
```bash
python -m rcsd_topo_poc t01-step4-residual-graph \
  --road-path <step4_input_roads.geojson> \
  --node-path <step4_input_nodes.geojson> \
  --out-root <out_root>
```

### Step5
```bash
python -m rcsd_topo_poc t01-step5-staged-residual-graph \
  --road-path <step4_refreshed_roads.geojson> \
  --node-path <step4_refreshed_nodes.geojson> \
  --out-root <out_root>
```

## 当前输出

### Step5A
- `step5a_pair_candidates.*`
- `step5a_validated_pairs.*`
- `step5a_rejected_pairs.*`
- `step5a_trunk_roads.*`
- `step5a_segment_body_roads.*`
- `step5a_residual_roads.*`

### Step5B
- `step5b_pair_candidates.*`
- `step5b_validated_pairs.*`
- `step5b_rejected_pairs.*`
- `step5b_trunk_roads.*`
- `step5b_segment_body_roads.*`
- `step5b_residual_roads.*`

### Step5 merged
- `step5_validated_pairs_merged.*`
- `step5_segment_body_roads_merged.*`
- `step5_residual_roads_merged.*`

### Step5 refreshed 基础文件
- `nodes.geojson`
- `roads.geojson`
- `nodes_step5_refreshed.geojson`
- `roads_step5_refreshed.geojson`
- `step5_summary.json`
- `step5_mainnode_refresh_table.csv`

## 后续使用建议
- 未来 `Step6` 默认从 Step5 输出目录中的 refreshed `nodes.geojson / roads.geojson` 继续启动
- 历史已有非空 `segmentid` 的 road，后续轮次默认不再参与工作图构建
