# Tasks: T10 FRCSD 质量检查专用流水线

- [x] T001 核对 T10/T11/T12 源事实、入口 registry 和目标文件写前体量。
- [x] T002 调整 Case runner `WITH_T12` stage/chain 为 `T06 -> T11 -> T12 -> T09`，默认链不变。
- [x] T003 调整 full runner stage index、resume order、manifest pipeline 和实际执行块顺序。
- [x] T004 新增 `scripts/t10_run_frcsd_quality_pipeline.sh`，固定 `RUN_T08=0/RUN_T12=1` 并复用 full runner。
- [x] T005 为专用入口增加冲突变量、显式 FRCSD target、可选 Case 边界和 resume 合同测试。
- [x] T006 更新 T10/T12 模块 SPEC、INTERFACE_CONTRACT 和 architecture 01~06 中的专用链事实。
- [x] T007 更新项目 SPEC/requirements/architecture、入口 registry 和 code-size audit。
- [x] T008 运行 T10/T12/受影响 T06 测试、shell syntax、CLI/entry help 和 compile 门禁。
- [x] T009 运行 1026960 新顺序端到端，核对 35/10/25/0 与 T06/T11/T09 业务等价。
- [x] T010 完成 CRS/拓扑/几何/审计/性能、无对象白名单、`git diff --check` 和内网边界审计。
- [x] T011 生成 validation summary，按已修改/已验证/待确认回报。
