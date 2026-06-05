# T01 高等级 Segment 业务迭代 Plan

## 范围

本轮只修改 T01 双向 residual 阶段的历史边界来源，以及 Step5 后 final fallback 的 residual road 覆盖范围。不会新增官方 CLI 或 scripts 入口，不触碰其它模块。

## 设计

1. 历史边界来源收敛
   - Step4 `collect_endpoint_pool_mainnodes` 的读取顺序调整为 `validated_pairs.csv -> endpoint_pool.csv`。
   - Step5 对 S2 / STEP4 同步使用 `validated_pairs.csv -> endpoint_pool.csv`。
   - 这样 `endpoint_pool.csv` 仍作为旧产物兼容，但不再让未成段 seed / terminate 变成 hard-stop。

2. final fallback 扩展
   - 新增 final fallback 候选收集函数，覆盖 `direction in {0,1,2,3}`。
   - `direction in {2,3}` 继续按有向 semantic endpoint 发布 `0-2单`。
   - `direction in {0,1}` 按 road 两端 semantic endpoint 发布 `0-2双`。
   - 保留 `segment_build_source=oneway_single_road_fallback`，新增 summary 的单向 / 双向 built road 计数。

3. 验证
   - 单元测试覆盖历史边界读取优先级和双向 final fallback。
   - XS2 / XS3 全链路 release 回归，记录 Segment count、unsegmented count、XS3 `1608731_1602185` 命中情况。

## 风险

- 历史 hard-stop 放松可能增加 Step4/Step5 candidate 数量，需要通过 XS2/XS3 和内网全量观察性能。
- same-stage arbitration 可能仍选择局部短 Segment；如出现该情况，再进入第二轮仲裁/高等级走廊优先级调整。
- final fallback 将更多 residual road 发布成 Segment，后续消费方需依赖 `segment_build_source` 区分兜底成果。

