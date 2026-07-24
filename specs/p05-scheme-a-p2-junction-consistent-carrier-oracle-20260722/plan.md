# P05-Scheme-A-P2-P0 实施计划

## 1. 数据流

```text
frozen skeleton + P1 truth-free carrier sources
  -> P2 joint candidate run
  -> immutable candidate manifest/hash
  -> P1 Segment labels + T06 Node truth (label-only)
  -> Segment Road truth selection
  -> JunctionUnit shared Node carrier solve
  -> Segment/Junction fallback + RealityChangeClue
  -> RoadGraph hard gate
  -> second independent run + determinism/resource/GIS audit
```

## 2. 文件设计

- `scheme_a_p2_models.py`：candidate/Oracle config 与稳定 schema。
- `scheme_a_p2_oracle.py`：candidate冻结、联合 Node carrier求解、fallback、RoadGraph和 run 工件。
- `scheme_a_p1_execution.py`：仅增加可选的显式 Node carrier override；默认行为保持不变。
- `__init__.py`：导出 P2 callable，不新增执行入口。

## 3. Candidate 阶段

1. 验证 P1 candidate 与 Scheme A baseline manifest/hash。
2. 只消费 frozen Segment/Junction 身份和 T01/proposal lineage。
3. 冻结全部 Segment Road candidate 引用。
4. 对 T01/proposal Node 生成 `node_id/source/mainnode_key/semantic_signature/artifact` option。
5. 输出 truth 使用计数 0、Movement 数 0 和候选 signature。

## 4. Oracle 阶段

1. 验证 candidate manifest/hash 后加载 Segment label-only truth。
2. 每个 Segment先选择个体 truth Road candidate；固有 unsafe 直接 SWSD fallback。
3. 对每个 JunctionUnit 收集所选 Road 的 access endpoint，求所有 Node 的共同 mainnode key。
4. 在共同 key 内优先选择与 T06 Node truth exact 的 candidate；无共同 key则 Junction fallback。
5. Road/Node hard gate 发现 Segment 局部冲突时只回退失败 Segment，再重新求解受影响 Junction。
6. 输出 joint exact、USE_RCSD retention、clue、fallback、逐 Case RoadGraph 与最终决策。

## 5. 验证顺序

1. SpecKit/source-of-truth 一致性。
2. 单元、隔离和破坏测试。
3. candidate Run A/B 与 hash 确定性。
4. Oracle Run A/B、49+2 RoadGraph 与业务指标。
5. QGIS CRS/几何审计、资源、完整 P05 回归和代码体量/入口治理。
6. validation summary 与项目/P05 source-of-truth 收口。

## 6. 非目标

- 不训练 scorer。
- 不处理 Movement。
- 不修改 T01–T12、T10 或生产主链。
- 不新增入口或把 Oracle payload 作为未来模型输入。

## 7. 完成结果

计划项已全部执行。Gate 0、Gate 1、Gate 3、Gate 4 通过；Gate 2 因 `USE_RCSD` truth retention=`0.165753 < 0.50` 未通过。最终决策为 `P05_SCHEME_A_P2_P0_UPSTREAM_CARRIER_NO_GO`，不进入 P2-P1 训练。
