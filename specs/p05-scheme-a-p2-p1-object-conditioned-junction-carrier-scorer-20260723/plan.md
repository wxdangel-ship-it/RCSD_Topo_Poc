# P05-Scheme-A-P2-P1 实施计划

## 1. 数据流

```text
Dataset-P0 role/lineage contract
  + Scheme-A P1 truth-free Segment candidates
  + PTO-P0 truth-free FINAL_NODE candidates
  -> frozen joint candidate manifest
  + Scheme-A effective Segment labels
  + Segment truth Road source-conditioned T01/proposal/OMIT Node labels
  -> grouped Segment/endpoint-Node dataset + compatibility Oracle
  -> 3 seeds × 5-fold object-conditioned scorer
  -> confidence/anomaly threshold + generic compatibility selection
  -> Segment/Junction fallback + RoadGraph safety
  -> deterministic replay + validation summary
```

## 2. 代码分层

- `scheme_a_p2_p1_models.py`：配置、schema和冻结门槛。
- `scheme_a_p2_p1_dataset.py`：候选冻结、特征、label join、fold和compatibility Oracle。
- `scheme_a_p2_p1_network.py`：Segment/Node共享的object-conditioned set scorer。
- `scheme_a_p2_p1_training.py`：fold-local vocabulary、normalization、inner validation、训练和score。
- `scheme_a_p2_p1_execution.py`：通用兼容选择、置信度/异常fallback和RoadGraph执行。
- `scheme_a_p2_p1_oof.py`：3 seeds × 5 folds、门禁、资源、确定性和工件。

每个源码/测试文件在写入前检查当前字节数；新文件保持低于60KiB，硬上限100KB。

## 3. 实施顺序

1. 冻结项目/模块源事实和接口合同。
2. 实现candidate-first dataset并验证零truth、零泄漏。
3. 执行label-only join和100% compatibility Oracle。
4. 实现模型、训练与held-out score。
5. 实现模型score驱动的通用兼容选择和fallback。
6. 执行开发run、修正实现缺陷。
7. 执行正式3 seeds × 5 folds和同seed重放。
8. 完成GIS、资源、测试、体量、入口和source-of-truth收口。

## 4. 验证层级

1. dataclass/schema/纯函数单元测试。
2. candidate/truth、fold和forbidden-feature破坏测试。
3. small-batch/listwise学习性和模型参数门。
4. 真实51 Case dataset/compatibility Oracle。
5. 真实3 seeds × 5-fold OOF与同seed重放。
6. 49+2 RoadGraph、GIS/CRS、资源、完整P05回归和治理审计。

## 5. 明确非目标

- 不训练或评价 Movement。
- 不生成新候选、不解决在线 proposal replay 性能。
- 不修改 T01–T12、T10 编排或生产主链。
- 不新增 Case、业务强规则或正式执行入口。
