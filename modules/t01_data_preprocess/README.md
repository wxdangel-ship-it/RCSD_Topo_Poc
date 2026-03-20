# T01 数据预处理模块

## 当前状态
- 当前阶段：`hierarchical boundary fix before poc closeout`
- 当前定位：
  - Step1：只发现 `pair_candidates`
  - Step2：做 `validated / rejected / trunk / segment_body / step3_residual`
  - Step4：在 Step2 基线刷新结果上做 residual graph 构建
  - Step5：在 Step4 刷新结果上做 `Step5A / Step5B` staged residual graph 构建
- 当前仍处于 POC 收敛阶段，尚未进入 closeout

## 当前已修复基线
- Step2 `segment_body` 已收紧为 pair-specific road body
- 右转专用道误纳入问题已修复
- `791711` 的 T 型双向退出误追溯已修复
- Step4 / Step5 已引入历史高等级边界 mainnode 终止逻辑
- Step2 已补齐双向 road 语义：
  - `direction = 0 / 1` 视为两条方向相反的可通行 road
  - 在 trunk / 最小闭环判定中，镜像往返同一组双向 road 可直接构成合法最小闭环
  - 该口径不额外引入新的 trunk 业务类型

## 当前已知 visual audit 修复重点
- Step4 错误 case `792579__55225234` 过去会穿越 `763111`
- 当前要求：
  - 更低等级轮次必须在更高等级历史路口中断
  - pair 搜索与 segment 收敛都必须使用同一套历史边界
  - 对 Step4 / Step5，凡是命中当前轮 `seed / terminate` 的节点，不得再作为当前轮 `through_node`
- 额外约束：
  - `mainnodeid = NULL` 的单点路口，其语义路口 ID 取自身 `id`
  - 若它命中当前轮输入规则，则必须作为合法语义路口进入 `seed / terminate`
  - 且当前轮不得再把它作为 `through_node`
- closeout 之前，优先继续修 visual audit 问题，不做 baseline handoff

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

## 关键输出

### Step4
- `step4_pair_candidates.*`
- `step4_validated_pairs.*`
- `step4_rejected_pairs.*`
- `step4_trunk_roads.*`
- `step4_segment_body_roads.*`
- `step4_residual_roads.*`
- `historical_boundary_nodes.geojson`
- `target_case_audit.json`
- refreshed `nodes.geojson / roads.geojson`

### Step5A / Step5B
- `step5a_*`
- `step5b_*`
- `step5_validated_pairs_merged.*`
- `step5_segment_body_roads_merged.*`
- `step5_residual_roads_merged.*`
- `historical_boundary_nodes.geojson`
- refreshed `nodes.geojson / roads.geojson`

## 使用说明
- 后续轮次默认继续消费最新一轮输出目录中的 `nodes.geojson / roads.geojson`
- 历史已有非空 `segmentid` 的 road 在更低等级轮次中默认从工作图剔除
- 若需要 visual audit，请优先叠加：
  - `historical_boundary_nodes.geojson`
  - `*_pair_links_validated.geojson`
  - `*_segment_body_roads*.geojson`
  - `*_residual_roads*.geojson`
