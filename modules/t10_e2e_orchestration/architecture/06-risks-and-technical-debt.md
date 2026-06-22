# 06 风险与技术债

## 1. 业务风险

- 如果把 T10 说成主业务链替代品，会混淆模块责任；T10 只编排和组织证据。
- 如果 Case runner 调用 T08，会把质量修复链和业务生产链混入同一职责。
- 如果 feedback 被直接用于 Step3 替换，会绕过 T03/T04/T05/T06 的正式审计。

## 2. 运行风险

- 内网全量脚本依赖大量路径和阶段输出，resume / RUN_STAGES / FINALIZE_EXISTING 需要准确区分。
- 旧 run 可能完成 T09 但缺顶层 T10 summary，需要 finalize-existing 补写完成态。
- Case package 切片如果缺道路端点节点，会导致本地 replay 拓扑不完整。

## 3. 结构债

T10 同时承担 Case packaging、runner、feedback、visual check 和 full pipeline 总控。后续扩展时应继续保持接口分层，避免把 full pipeline 脚本的内网路径假设写入 callable 契约。

## 4. 治理缺口

真实数据下的 feedback iteration 质量、全量审计口径和跨模块 handoff 稳定性仍需持续收敛。T06 visual check 目前是 audit-only 索引，后续可补充自动化拓扑质量评估，但不能替代模块正式审计。
