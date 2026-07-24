# P05-Scheme-A-P2-P0 研究结论

## 1. P1 归因

P1 的对象级 Segment macro-F1 接近 1，但 truth-exact execution coverage 仅约 0.369。主要原因不是模型未学会对象标签，而是 Segment candidate 把 Road 和共享 Node绑定，且 proposal Junction 风险被提升为整个对象 `hard_unsafe`。

## 2. 启动前只读诊断

- 仅将风险降为 candidate-specific 并复用整图 hard gate时，Segment 安全非 fallback coverage 约 0.5877，49+2 终态保持。
- 严格按 Junction 冲突全部 SWSD时，joint truth exact 仍可超过 0.50，但大部分 exact 来自 KEEP_SWSD，不能证明 RCSD 替换价值。
- 将共享 Node 从 Segment Road bundle中分离后，现有候选的 `USE_RCSD` 保留能力必须由正式 Oracle 独立量化；若低于 0.50，应判 upstream carrier candidate不足，而不是继续训练 scorer。

因此本阶段必须先做联合 candidate/Oracle，不得直接扩大 P1 模型。
