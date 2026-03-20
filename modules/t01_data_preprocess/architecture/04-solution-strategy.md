# 04 方案策略

## 状态
- 当前状态：`模块级方案策略说明`
- 来源依据：
  - official runner
  - staged residual graph 实现
  - 三样例活动基线

## 主策略
1. 模块开始先建立 working Nodes / Roads，并执行环岛预处理
2. 首轮通过 Step1 / Step2 / Step3 完成高等级双向路段提取与 refresh
3. 通过 Step4 / Step5A / Step5B / Step5C 在 residual graph 上继续逐轮向低等级扩展

## 降级与失败策略
- 失败条件：
  - working fields 缺失
  - freeze compare 不一致
  - 关键样例结果回退
- 降级方式：
  - 保留历史归档基线，不直接覆盖活动基线
  - 仅生成 candidate 或差异报告，等待用户确认
- 诊断要求：
  - `debug=true` 时输出 bootstrap / roundabout / step2 / step4 / step5 审计层
  - 对 trunk gate、side gate 和 endpoint pool 滚动提供可追溯产物

## 文档策略
- 稳定阶段链属于 `architecture/*`
- 参数类别、输出文件和验收标准由 `INTERFACE_CONTRACT.md` 承担
- `README.md` 提供简版运行说明
