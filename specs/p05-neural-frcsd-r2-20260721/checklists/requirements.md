# Requirements Checklist: P05-R2

## 产品

- [x] 最终目标仍为 T06 Step3 语义 RoadGraph。
- [x] R2 成功与生产替代明确区分。
- [x] Gate 1/2/3 的停止和归因规则明确。
- [x] 暂不要求新增 Case。

## 架构

- [x] Road/Node edit-set 与精确 T05 pointer 边界明确。
- [x] oracle label-only 与推理输入边界明确。
- [x] generic constraint 不含业务内容决策。
- [x] T07 默认关闭。

## 研发

- [x] 仅新增 P05 callable，不新增正式入口。
- [x] 资源、依赖、run 和输出合同明确。
- [x] 写入前完成每个目标源码文件字节数检查。
- [x] 实现后所有源码低于 100KB并同步 code-size audit。

## 测试与 QA

- [x] oracle roundtrip、破坏测试、pointer、模型与 OOF 范围明确。
- [x] CRS、拓扑、几何语义、追溯和性能五项明确。
- [x] Gate 1 真实 51 Case 证据完成。
- [x] Gate 2 small-batch 证据完成。
- [x] Gate 3 grouped OOF 证据完成并按门禁形成 no-go。
- [x] FR/SC validation summary 完成。
