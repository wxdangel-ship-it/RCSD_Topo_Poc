# 01 Introduction And Goals

## 1. 目标

T10 的目标是为 RCSD_Topo 建立端到端业务流程编排与 Case 级证据组织能力。

v1 目标：

- 固化 Case runner `T01 -> T07 Step1/2 -> T03 -> T04 -> T05 -> T07 Step3 -> T06 -> T09` 编排链路。
- 明确 T08 独立前置运行，不由 T10 v1 callable 或 Case runner 调用；内网全量总控可把 T08 作为独立前置阶段串联。
- 建立显式文件级 handoff slot。
- 建立以 SWSD 语义路口 ID 和半径为范围的 Case evidence package manifest。
- 建立 Case 候选建议、多个 CaseID 打包、自动分片和解包重组能力。

## 2. 成功标准

- 能生成稳定 workflow plan。
- 能审计目录型 handoff 并报错。
- 能生成只包含外部输入、不包含模块间中间产物的 Case package manifest。
- 能从 SWSD semantic junction inventory 与 selector evidence 生成候选 Case。
- 多 Case 包解包后能恢复 `cases/<case_id>/` 目录。
- 不新增未登记执行入口。
