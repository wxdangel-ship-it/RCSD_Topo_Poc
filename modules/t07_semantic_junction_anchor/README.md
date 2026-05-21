# T07 Semantic Junction Anchor

`t07_semantic_junction_anchor` 是 T02 Step1 / Step2 的语义路口级重构模块。当前只做 `has_evd / is_anchor / anchor_reason`，不处理 Segment。

## 当前范围

- Step1：基于 `nodes` 与 `DriveZone` 计算代表 node 的 `has_evd`。
- Step2：基于 `nodes` 与 `RCSDIntersection` 计算代表 node 的 `is_anchor / anchor_reason`。
- `kind_2` 只使用代表 node 字段。
- 仅处理代表 node `kind_2 in {4, 8, 16, 64, 128, 2048}`。

## 非目标

- 不读取、生成或统计 `segment.gpkg`。
- 不解析 `pair_nodes / junc_nodes`。
- 不输出 `segment.has_evd`。
- 不生成虚拟路口面。
- 不执行 div/merge polygon。
- 不新增 repo CLI 或脚本入口。

## 当前入口状态

当前模块只完成正式文档登记，后续实现仅允许模块内 callable runner，除非另行授权入口治理变更。

计划 callable runner：

```python
from rcsd_topo_poc.modules.t07_semantic_junction_anchor import (
    run_t07_semantic_junction_anchor,
)
```

上述 runner 当前尚未实现。

## 关键规则

- 语义路口按 `mainnodeid` 聚合；空 `mainnodeid` 退化为 singleton。
- 多节点组代表 node 必须满足 `id == mainnodeid`。
- `has_evd / is_anchor / anchor_reason` 只写代表 node。
- `kind_2` 不在 `{4, 8, 16, 64, 128, 2048}` 时，三个业务字段均为 `NULL`。
- `has_evd = yes` 才进入 Step2。
- Step2 保留 T02 `fail1 / fail2` 语义，且 `fail2 > fail1`。
- `kind_2 = 64` 全组命中 `RCSDIntersection` 时 `anchor_reason = roundabout`。
- `kind_2 = 2048` 全组命中 `RCSDIntersection` 时 `anchor_reason = t`。

## 输出

计划 Step1 输出：

- `nodes.gpkg`
- `t07_step1_summary.json`
- `t07_step1_audit.csv/json`
- `t07_step1_perf.json`

计划 Step2 输出：

- `nodes.gpkg`
- `node_error_1.gpkg/csv/json`
- `node_error_2.gpkg/csv/json`
- `t07_step2_summary.json`
- `t07_step2_audit.csv/json`
- `t07_step2_perf.json`

## 文档

- 稳定契约：[INTERFACE_CONTRACT.md](INTERFACE_CONTRACT.md)
- 架构说明：[architecture/](architecture/)
- 变更任务书：[../../specs/t07-semantic-junction-anchor-step12/](../../specs/t07-semantic-junction-anchor-step12/)
