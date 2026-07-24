# P05-Scheme-A-P2-P0 验收总结

## 结论

本阶段已完成，正式决策为 **`P05_SCHEME_A_P2_P0_UPSTREAM_CARRIER_NO_GO`**。

这不是 RoadGraph 安全失败，也不是神经网络整体不适用。联合 Oracle 已证明在冻结业务骨架和安全 fallback 下可以稳定生成 49 个合法 RoadGraph，并精确保留 2 个已知 SWSD 基线失败；但现有 T01/proposal Node carrier option 只能保留 `16.5753%` 的正确 RCSD Segment 组合，尚不足以训练下一阶段联合 scorer。

## 正式证据

- Candidate A/B：`p05_scheme_a_p2_candidate_20260722_01/_02`。
- Oracle A/B：`p05_scheme_a_p2_oracle_20260722_05/_06`。
- 早期 Oracle `_01/_02` 暴露跨 Case 对象地址缓存导致的审计 hash 不确定性；`_03/_04` 验证修正，最终 `_05/_06` 同时补齐 expected-failure 专属 RealityChangeClue。旧 run 保留为诊断证据，不作为正式结论。

## 门禁结果

| 门禁 | 结果 | 证据 |
|---|---|---|
| Gate 0 范围/隔离 | PASS | 51 Case、8,863 Segment；Movement candidate/decision/evaluation=0；truth-derived candidate/feature=0；骨架 mutation=0；CRS=`EPSG:3857` |
| Gate 1 联合真值 | PASS | 9,042 Junction records；candidate truth reachability、lineage/hash 完整；每个冲突显式记录，不做 silent normalize |
| Gate 2 安全覆盖/价值 | **FAIL** | joint exact=`4,844/8,863=0.546542` 通过；`USE_RCSD` retention=`363/2,190=0.165753` 未通过；错误替换=0、unsafe ADVANCE_RIGHT 发布=0 |
| Gate 3 RoadGraph 安全 | PASS | 49 `LEGAL` + 2 精确 `EXPECTED_FAIL`；新增失败=0；repair/silent fix=0 |
| Gate 4 确定性/资源 | PASS | Candidate、Segment、Junction、Clue、RoadGraph、metrics signature A/B 全部一致；P95 `0.724s`、max `3.180s`、RSS `<1.21GB`、无需 GPU |

最终 fallback 为 5,146 个 Segment 终态，其中 Junction fallback 2,812、Segment fallback 2,334；输出 3,933 条 RealityChangeClue。两个 expected-failure Case 均有专属 Case 级 clue，精确记录缺失 Node 与有向边。

## GIS / QA

QGIS 3.40.14 对 51 Case 的 204 个 T01/proposal Road/Node 图层完成全量读取：78,470 个要素，非法图层、CRS 不一致、几何类型不一致、空几何和 GEOS 非法几何均为 0。P2-P0 不生成新几何图层，只输出引用既有 payload 的逻辑 RoadGraph，因此 road-polygon overlay 明确为 `NOT_APPLICABLE`；拓扑由 RoadGraph 引用、方向和有向边 hard gate 验证。

完整 P05 回归：`145 passed`。P05 核心 122 个源码/测试文件与本 SpecKit 一次性 QGIS 脚本均低于 60KiB/100KB；未新增正式入口。

## 后续边界

P2-P1 scorer 不得启动。若继续研究，需要用户另行批准一个“上游 carrier option 扩展”阶段：只扩展可选 Node carrier 表达和证据，不新增/删除 Segment、不改变 Junction—Segment 关系、不修改 Movement、不使用 T06 业务规则直接决定输出。
