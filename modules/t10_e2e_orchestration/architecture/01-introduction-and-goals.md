# 01 引言与目标

## 1. 文档定位

本文件说明 T10 的架构背景、目标和边界。模块需求以 `SPEC.md` 为准，稳定接口以 `INTERFACE_CONTRACT.md` 为准，编排与 Case 证据策略见 `03-solution-strategy.md`。

## 2. 模块定位

T10 是端到端业务流程编排与 Case 级证据组织模块。它不定义 T01-T09 / T11 / T12 的算法规则，也不替代项目级主业务链。T10 的价值在于把外部输入、模块 handoff、Case package、Case replay、feedback、visual check、full pipeline manifest 和 summary 组织成可追溯的证据链。

## 3. 目标

- 固化 T10 v1 Case runner 编排范围：`T01 -> T07 Step1/2 -> T03 -> T04 -> T05 -> T06 -> T11 -> T09`。
- T11 为 T06 后、T09 前的 audit-only 必经阶段，不改变 T09 对 T06 业务产物的直接依赖。
- T12 是显式开启的 audit-only 可选阶段，位于 T11 后、T09 前；默认关闭，不改变现有业务流程。
- 明确 T07 Step3 只作为可选兼容 relation 补锚阶段，不纳入 Case runner 默认主链。
- 以 SWSD semantic junction id 组织 Case package 和本地 replay。
- 为每个阶段记录显式输入、输出、命令、日志、状态和耗时。
- 输出 T06 funnel、visual check summary 和 upstream feedback package。
- 支持 innernet full pipeline 的阶段级 manifest、summary、resume 和 finalize-existing。
- 提供固定跳过 T08、启用 T12 的 F-RCSD 质量检查专用入口，复用同一 full runner。

## 4. 非目标

- 不改变项目级主业务链。
- T10 v1 callable 与 Case runner 不调用 T08。
- 不修改 T01-T09 / T11 / T12 算法。
- 不把 feedback 直接变成 Step3 替换白名单。
- 不把未执行的内网操作表述为已执行。

## 5. 架构边界

T10 有三个层级：Case package / Case runner 面向局部复现；feedback 和 visual check 面向 Case 证据与上游迭代；innernet full pipeline 脚本面向全量阶段总控。三者都只组织调用和证据，不改变模块算法。
