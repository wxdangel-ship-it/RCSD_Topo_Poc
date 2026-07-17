# T08 Agent Guardrails

本文件只保留 `t08_preprocess` 的 Agent 局部红线；模块源事实以 `SPEC.md`、`INTERFACE_CONTRACT.md` 与 `architecture/*` 为准。

- T08 是正式预处理、质检、修复和显性化模块，不是临时工具箱。
- 不根据局部样本反推 Road / Node 字段语义。
- Tool4 不做契约外拓扑重塑；只按契约修复路口类型。
- T08 成果输出文件名必须在扩展名前以 `_toolX` 结尾；当前已登记特例为 Tool1 同 stem 格式转换、Tool10 `Traj/raw_dat_pose.gpkg`，以及 Tool11 保留 Patch 数据整理业务文件原名；三个工具的 summary 仍分别以 `_tool1 / _tool10 / _tool11` 结尾。
- 不修改 T00 Tool4 / Tool5 契约，除非任务明确授权。
- 不在模块根目录新增 `SKILL.md`。
