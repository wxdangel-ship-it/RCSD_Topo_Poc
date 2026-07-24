# P05-Scheme-A-P2-P3-P1 实施计划

## 阶段 1：冻结合同

1. 核对用户授权、工作树、Movement/Git/T01–T12 边界。
2. 冻结 P2-P3-P0 及依赖工件的 manifest/hash。
3. 冻结稳定错误对象、fold 2 和 13 clue-only 审计分母。

## 阶段 2：源事实与数据盘点

1. 读取 T01/T07/T03/T04/T05/T06 项目级和模块级源事实。
2. 解析实际 artifact 的生成链路、输入依赖、CRS 和时点。
3. 将所有潜在字段归入 `INFERENCE_ALLOWED/LABEL_ONLY/FORBIDDEN_LEAKAGE/UNAVAILABLE`。
4. 盘点 `E:\TestData\POC_Data` 中当前 51 Case 之外的独立验证证据。

## 阶段 3：逐对象失败归因

1. 复盘稳定 false-use Segment 的所有 candidate/score/compatibility/上游证据。
2. 对 fold 2 全量 Segment 形成 accept/fallback/clue 明细和跨 fold 对照。
3. 对 13 clue-only 对象逐 seed 解释捕获与漏报。
4. 区分直接因果证据、相关软信号和当前不可用证据。

## 阶段 4：可复现验证

1. 实现 P05 内部只读审计 callable 和专项测试。
2. 完成正式 Run A/B。
3. 验证内容确定性、CRS/拓扑/几何零修改、资源和性能。
4. 输出 `MODEL_RESTART_GO/EVIDENCE_NO_GO/AUDIT_NO_GO`。

## 阶段 5：收口

1. 形成 validation summary。
2. 结论稳定后同步 P05 项目级和模块级阶段事实。
3. 不提交、不推送。

