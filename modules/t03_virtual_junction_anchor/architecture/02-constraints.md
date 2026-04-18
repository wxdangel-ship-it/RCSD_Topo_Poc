# 02 Constraints

- 正式输入契约固定为 Anchor61 `case-package`
- `Step4-5` 必须消费冻结 Step3 run root，不得回写 Step3
- 所有空间判定统一到 `EPSG:3857`
- `Step3` 仍必须严格遵守 A-H；`Step4-5` 不得用 cleanup/trim 反证 Step3 成立
- 不修改 T02 正式业务行为
- 不提交 `outputs/_work`、批量 PNG、线程同步文件到 Git
