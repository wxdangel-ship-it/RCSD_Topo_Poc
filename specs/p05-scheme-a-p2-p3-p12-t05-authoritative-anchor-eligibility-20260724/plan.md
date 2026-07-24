# 实施计划

## specify

- 冻结 T05 为所有正式 Junction 锚定的唯一发布依据；
- 冻结 `STANDARD pair_nodes` 与 `ADVANCE_RIGHT @node_id` 两侧目标解析；
- 冻结人工 `USE_RCSD` 业务真值与当前正式替换资格分离；
- 冻结 RCSD 缺失不产生 RealityChangeClue。

## plan

1. 校验 P11 接受工件、Scheme-A inventory、candidate groups 与三个 T10 Case；
2. 为 19 个对象解析冻结两侧目标，不做名称或几何猜测；
3. 读取 T05 relation/cardinality/blocking/graph consumability 证据；
4. 为既有 `USE_RCSD` candidate 读取 Road/Node 引用并审计两侧连接兼容性；
5. 将人工业务结论、T05 anchor 状态、carrier 可用性和当前发布资格分列；
6. 输出 19 对象 ledger 与最小 T05 lineage repair queue；
7. 输出 metrics、summary、validation report、manifest 和确定性 signature；
8. 完成专项测试、正式双跑、完整 P05 回归、GIS/资源和文件体量审计。

## implement 边界

- 只新增 P05 内部只读 callable 与专项测试；
- 不修改 P8/P9/P10/P11 实现或历史工件；
- 不修改 T01–T12，不新增 CLI、script、T10 stage、`__main__.py` 或 Makefile target；
- 不训练、不调阈值、不更新模型；
- 不提交或推送 Git。

## 资源估算

- 训练/GPU：0；
- 读取三个 Case 的 T01/T05 关系和 Road/Node 图，预计 wall time 小于 2 分钟；
- 峰值 RAM 预计低于 1 GiB；
- 正式双跑与专项测试预计小于 5 分钟。
