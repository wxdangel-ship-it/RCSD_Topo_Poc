# 实施计划

## 1. specify

- 冻结carrier-only promotion、Clue零消费和无来源零残差。
- 冻结Control/Treatment、3×5 OOF、四类decision和资源预算。

## 2. plan

1. 校验P7/P8/Dataset-P1/P4/P5 lineage与6,275对象join。
2. 构建train-fold-only source vocabulary、数值编码和multi-source池化。
3. 以P5超参数训练602维Movement-free Control。
4. 冻结Control，训练`<=300K` source residual adapter。
5. 复用既有access/Clue/Node/Junction/RoadGraph执行链，Clue不读取source。
6. 分Control/Treatment、applicable/non-applicable、scorer/final计算指标。
7. 执行3 seeds × 5 Case folds、正式Run A/B、完整P05回归和资源审计。
8. 根据Gate 2/3分别形成promotion与完整carrier结论。

## 3. implement边界

- 只新增P05内部P9 dataset/model/OOF/审计和测试；
- 不新增CLI、script、T10 stage或正式入口；
- 不修改T01–T12实现、接口或工件；
- 不处理Movement，不改变fallback、RoadGraph或业务骨架。

## 4. 资源估算

- Control：15个fold模型，2.818M级；
- Treatment：15个fold adapter，trainable参数`<=300K`；
- 单次正式全流程预计8–12分钟，硬预算15分钟；
- CPU RAM预计3–5GiB，硬预算8GiB；
- GPU=0；
- Run A/B合计预计16–24分钟，工件增量预计低于1.5GiB。
