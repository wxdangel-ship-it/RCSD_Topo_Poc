# 018 - Step6 segment aggregation POC

## 背景
- 当前 `Step1–Step5C` 已能产出 refreshed `nodes / roads` 与 road-level `segmentid / s_grade`。
- 但现有正式产物仍主要停留在 road-level，不利于直接按 Segment 审查：
  - Segment 主体几何
  - Segment 内含路口
  - Segment 中间仍向外分支的路口
  - Segment 级 `s_grade / grade_2 / kind_2` 合理性

## Step6 业务目标
- 基于最新 Step1–Step5C 成果，聚合生成 `segment.geojson`
- 输出被 Segment 完全内含的 `inner_nodes.geojson`
- 输出需人工评估的 `segment_error.geojson`
- 提供 `segment_summary.json / segment_build_table.csv / inner_nodes_summary.json` 便于审计

## 图层定义

### segment.geojson
- 每个非空 `roads.segmentid` 聚合为一条 Segment
- `geometry` 统一输出为 `MultiLineString`
- 关键字段：
  - `id`
  - `s_grade`
  - `pair_nodes`
  - `junc_nodes`
  - `roads`

### inner_nodes.geojson
- 若某语义路口的全部允许 road 都属于同一个 Segment，则该语义路口不写入 `junc_nodes`
- 该语义路口组内所有 node 完整复制到 `inner_nodes.geojson`
- 仅追加 `segmentid` 便于追溯

### segment_error.geojson
- 记录需人工评估的异常 Segment
- 当前至少承载：
  - `s_grade = "0-0双"`，但中间 `junc_nodes` 仍出现 `grade_2 = 1 且 kind_2 = 4`

## junc_nodes / inner_nodes 划分原则
- 语义路口统一按：
  - `working_mainnodeid` 有值时使用 `working_mainnodeid`
  - 否则使用 node 自身 `id`
- `pair_nodes` 由 `segmentid = A_B` 直接给出，顺序按 `A_B`
- 对覆盖到的内部语义路口：
  - 若其全部允许 road 都在当前 segment 内，则归入 `inner_nodes`
  - 若仍有允许 road 指向当前 segment 之外，则归入 `junc_nodes`

## Segment 级反查规则

### 规则 1：s_grade 轻调整
- 若 segment 两端 `pair_nodes` 对应语义路口 `grade_2` 均为 `1`
- 且当前 `s_grade != "0-0双"`
- 则将该 segment 的 `s_grade` 轻调整为 `"0-0双"`

### 规则 2：0-0双 中间路口约束
- 若 segment 最终 `s_grade = "0-0双"`
- 且其 `junc_nodes` 出现 `grade_2 = 1 且 kind_2 = 4`
- 则输出到 `segment_error.geojson`

## 当前未覆盖内容
- 不回改 `Step1–Step5C` 主逻辑
- 不在 `Step6` 中重新做构段搜索
- 不在 `Step6` 中引入新的 seed / terminate / barrier 语义
- 同一 `segmentid` 下 `s_grade` 多值冲突当前直接 fail fast，不做自动修复
