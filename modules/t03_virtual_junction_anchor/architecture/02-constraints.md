# 02 Constraints

- 正式输入契约固定为 Anchor61 `case-package`
- `Step4-7` 必须消费冻结 Step3 run root，不得回写 Step3
- 所有空间判定统一到 `EPSG:3857`
- `Step3` 仍必须严格遵守 A-H；`Step4-7` 不得用 cleanup/trim 反证 Step3 成立
- `Step5` 不再向 `Step6` 提供 hard polygon foreign context
- `Step6` 当前 hard negative mask 只消费 road-like `1m` 掩膜，不把 node 类 foreign 变成 hard subtract
- 不修改 T02 正式业务行为
- 不新增 T03 repo 官方 `Step67` CLI
- 不提交 `outputs/_work`、批量 PNG、线程同步文件到 Git
