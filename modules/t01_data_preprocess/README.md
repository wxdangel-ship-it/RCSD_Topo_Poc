# T01 数据预处理模块

## 当前状态
- 当前状态：`POC 已结束，accepted baseline 已固化`
- 当前模块定位：
  - Step1：只发现 `pair_candidates`
  - Step2：完成首轮 `validated / rejected / trunk / segment_body / step3_residual`
  - Step4：在 refreshed 基线上做 residual graph 外层轮次扩展
  - Step5：在 Step4 refreshed 基线上做 `Step5A / Step5B / Step5C`
- 后续工作将转入正式模块完整构建

## 当前 accepted baseline
- Step2 `segment_body` 已收紧为 pair-specific road body
- 右转专用道误纳入问题已修复
- `791711` 的 T 型双向退出误追溯已修复
- trunk 语义已补齐：
  - 双向 road 视为两条方向相反的可通行 road
  - split-merge 分合混合通道可成立
  - semantic-node-group closure 可成立
- Step4 / Step5 已纳入历史高等级边界 mainnode
- `mainnodeid = NULL` 单点路口按独立语义路口处理
- residual graph 已成为后续轮次正式工作方式

## 当前推荐入口

### 首轮
```bash
python -m rcsd_topo_poc t01-step2-segment-poc \
  --road-path <roads.geojson> \
  --node-path <nodes.geojson> \
  --strategy-config <step1_pair_s2.json> \
  --formway-mode strict \
  --out-root <out_root>
```

### 首轮刷新
```bash
python -m rcsd_topo_poc t01-s2-refresh-node-road \
  --road-path <roads.geojson> \
  --node-path <nodes.geojson> \
  --s2-path <step2_run_root> \
  --out-root <out_root>
```

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

说明：
- 当前真正推荐的 repo 级入口仍是 `python -m rcsd_topo_poc`
- 上述四个子命令是 T01 当前 accepted baseline 的推荐运行链路
- 历史实验入口可保留，但不再作为当前主入口说明

## 当前推荐输入基线
- 后续轮次与后续模块构建，推荐直接消费：
  - 最新一轮 refreshed `nodes.geojson`
  - 最新一轮 refreshed `roads.geojson`
- 若需要继续多轮构段：
  - road 中已有非空 `segmentid` 的对象在工作图中剔除
  - 使用 residual graph 继续推进

## 当前推荐输出基线
- 当前推荐输出基线为：
  - Step5 refreshed `nodes.geojson`
  - Step5 refreshed `roads.geojson`
- 推荐同时保留对应审计结果：
  - `step5_validated_pairs_merged.*`
  - `step5_segment_body_roads_merged.*`
  - `step5_residual_roads_merged.*`
  - `historical_boundary_nodes.*`
  - `step5_summary.json`

## 当前推荐审计材料
- 首轮：
  - `pair_validation_table.csv`
  - `segment_summary.json`
- Step4：
  - `historical_boundary_nodes.geojson`
  - `target_case_audit.json`
  - `step4_pair_validation_table.csv`
- Step5：
  - `step5_validated_pairs_merged.csv`
  - `step5_mainnode_refresh_table.csv`
  - `step5_summary.json`

## 后续正式模块完整构建从哪里继续
- 从当前 accepted baseline 继续
- 具体起点为：
  - 最新一轮 Step5 refreshed `nodes.geojson / roads.geojson`
  - 已固化的 Step1 / Step2 / Step4 / Step5 业务语义
- 后续正式构建待办：
  - Step6
  - 单向 Segment
  - Step3 完整语义归并
  - 完整多轮闭环治理
  - 统一编排入口
  - 更完整的测试 / 回归 / 验收体系
