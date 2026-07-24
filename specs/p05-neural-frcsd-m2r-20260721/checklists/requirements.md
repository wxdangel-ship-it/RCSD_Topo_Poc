# Requirements Checklist: P05 M2R

## 产品

- [x] 最终目标是 T06 Step3 语义 RoadGraph，不是中间 replaceable。
- [x] T03/T04/T05/T06 为必选学习任务，T07 为可选消融。
- [x] 成功与实验完成/no-go 明确区分。
- [x] 不宣称生产替代。

## 架构

- [x] 共享编码器、任务 Head、free/constrained 解码边界明确。
- [x] 通用约束白名单不包含业务策略。
- [x] T01 与正式 T03-T07 模块边界明确。
- [x] 已访问 test 不再作为盲测，使用 grouped OOF。

## 研发

- [x] 只新增 P05 callable 和小文件，不新增正式入口。
- [x] 参数、依赖、资源和输出合同明确。
- [x] 实现前完成每个目标源码文件字节数检查。
- [x] 实现后所有源码小于 100KB并同步 code-size audit。

## 测试

- [x] 标签、mask、泄漏、各 Head、解码和物化测试范围明确。
- [x] small-batch overfit 为必选门禁。
- [x] free/constrained 使用同一 logits。
- [x] 测试先失败后实现并保留结果。

## QA

- [x] CRS、拓扑、几何语义、审计、性能五项齐全。
- [x] 逐 Case、最差 Case、类别覆盖和异常清单齐全。
- [x] 不以目录名推断标签、不重跑规则伪造真值。
- [x] 完成 FR/SC 逐项验证并形成 validation summary。

## 就绪判定

- [x] 无待澄清产品决策。
- [x] 数据范围和排除项已冻结。
- [x] 用户已正式授权启动。
