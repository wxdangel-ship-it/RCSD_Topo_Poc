# 03 Context And Scope

## 上下文

T02 的 Step1 / Step2 当前同时包含两类候选来源：

- `nodes` 语义路口集合。
- T01 `segment` 中 `pair_nodes + junc_nodes` 引用的路口集合。

T07 从 T02 中抽取语义路口级需求，只保留 `nodes` 语义路口集合，不再让 Segment 引用关系参与候选扩展、结果写值或统计。

## 范围内

- 语义路口组装。
- 代表 node 识别。
- `DriveZone` 命中判定。
- `RCSDIntersection` 命中判定。
- `has_evd / is_anchor / anchor_reason` 写值。
- `node_error_1 / node_error_2` 冲突审计。
- 语义路口级 summary / audit / perf。

## 范围外

- Segment 输入、输出和统计。
- T02 Stage3 虚拟路口面。
- T02 Stage4 分歧 / 合流虚拟路口面。
- T03 / T04 downstream `fail3 / fail4 / fail4_fallback` 写回。
- T05 surface fusion 或 relation 发布。
- repo 官方 CLI。
- 除 `scripts/t07_run_semantic_junction_anchor_innernet.sh` 外的其它 repo 级脚本入口。
