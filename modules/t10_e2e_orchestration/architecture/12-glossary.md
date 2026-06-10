# 12 Glossary

| 术语 | 含义 |
|---|---|
| T10 | 端到端业务流程编排与 Case 证据组织模块。 |
| T10 v1 chain | `T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09`。 |
| T08 policy | T08 独立前置运行，T10 v1 不调用 T08。 |
| external input | T10 外部输入，包括 T08 独立运行后的成果和原始 RCSD / SWSD 支撑数据。 |
| handoff | T01-T09 模块间中间产物。 |
| directory-only handoff | 只配置模块输出目录、由下游自行猜测文件的输入方式；T10 v1 拒绝该模式。 |
| Case evidence package | 以 SWSD 语义路口 ID 与半径为范围的证据包。v1 为 manifest-first。 |
| CaseID | SWSD semantic junction id；坐标不是 CaseID。 |
| selector evidence | 用于建议打包哪些 Case 的错误、失败或审计证据，不进入最终 Case payload。 |
| inventory-only | 仅从 SWSD nodes inventory 生成的可打包语义路口，不表示问题成立。 |
| problem-candidate | selector evidence 命中的候选 Case，仍需后续分析确认问题真实性。 |
