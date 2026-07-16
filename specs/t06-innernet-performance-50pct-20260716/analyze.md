# Analyze: T06 全量内网性能恢复

## 1. 源事实一致性

- 项目级目标要求 T06 先证明 replacement plan，再执行替换，并保留 final topology/surface 审计。
- T06 模块契约允许性能优化，但禁止改变 replacement plan、problem registry、Step3 relation 和最终 QA 语义。
- 本轮只优化 T06 内部实现与测试，不改变官方 callable、CLI、入口、依赖或字段语义。
- 未发现任务书与源事实冲突，不触发硬停机。

## 2. 复杂度审计

- `_build_junction_states`: 当前为 `O(added_rcsd_nodes × junction_states)`，全量六轮约 207 亿组合检查。
- `_relation_context`: 调用方重复按 Segment 扫描全部 relation rows。
- `_anchor_statuses`: 非 replaceable Segment 重复扫描 Step1/Step2 rows，并在循环内构造新列表。
- `_reachable_any`: 相同 graph 上重复 BFS。
- surface-aware plan release: 当前日志证明完整 Step3 运行六轮，所有未缓存的计算被乘以六。

## 3. 体量与入口

- 本轮不新增正式入口。
- 当前目标文件均低于 100KB；任何源码/测试写入前仍需逐文件记录实时 bytes。
- 若修改后任一文件达到或超过 60KiB，必须同轮拆分或更新 `code-size-audit.md`。

## 4. 基线分层

- 六例冻结性能/业务：`outputs/baselines/t10_full_96b0ea5_20260710_060735` 与上一轮 current/candidate evidence。
- 当前代码局部基线：本工作树 `f870a83` 新实跑结果。
- 当前内网全量基线：`t10_innernet_full_no_t08_20260713_154417`，诊断 bundle id `f5bba49122c4d641`。

## 5. 完成判定

局部测试、`1885118` 和六例只能证明业务等价与局部性能；正式完成必须同时取得全量内网同环境 T06 `<=50%`、peak RSS 不回退、业务/GIS/审计通过证据。
