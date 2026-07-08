# T01 Segment 形态控制业务迭代 Tasks

- [x] T001 基于最新 `origin/main` 建立临时 worktree 与隔离分支。
- [x] T002 阅读 `README.md`、T01/T06 模块源事实、入口治理与文件体量约束。
- [x] T003 定位当前 1885118 基线中长 Segment 与 T06 失败关系，区分 T01 形态问题和 T05/T06 关系问题。
- [x] T004 新增 T01 Segment 形态控制组件，覆盖内部路口转角和道路等级不一致拆分。
- [x] T005 将形态控制接入 oneway completion 后、Step6 aggregation 前的内部 pipeline。
- [x] T006 增加 summary 与 road 审计字段。
- [x] T007 增加聚焦单元测试。
- [x] T008 更新 T01 源事实文档，说明形态控制边界、字段、审计与非目标。
- [x] T009 运行 T01 相关单元测试。
- [x] T010 运行 1885118 T01/T06 rerun 并对比当前基线。
- [x] T011 1885118 通过后，运行 Segment20 与其余 5 case 回归。
- [x] T012 汇总已修改、已验证、待确认，并说明是否建议刷新冻结基线。
