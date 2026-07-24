# P05-Scheme-A-Dataset-P0 数据模型

- `DatasetP0ModuleRole`：模块、业务职责、训练角色、是否允许作为模型输入/标签/候选/验证，以及禁止解释。
- `DatasetP0SampleRecord`：M0 sample、family、business ID、scope、fold、权重、task mask和批准排除状态。
- `DatasetP0ArtifactRecord`：artifact路径/hash、来源模块、训练角色、label-only和推理可用性。
- `DatasetP0TaskTargetRecord`：T03/T04/T05/T06/T07目标的availability、trust、weight、mask和原因。
- `DatasetP0CandidateSource`：候选stage、source role/kind、来源模块、T01 fallback或非T01 proposal分类。
- `DatasetP0SegmentReachability`：Segment truth target、Road ID集合、candidate覆盖、USE_RCSD非T01覆盖、mask与归因。
- `DatasetP0CaseReachability`：Case final Road/Node对象数、候选覆盖率、Segment联合exact和安全终态。
- `DatasetP0Summary`：Gate 0~4指标、历史P2对照、最终decision和signature。

全部输出只作P05实验label/candidate/audit，不构成T01-T12 source-of-truth或生产输入。
