# 06 风险与技术债

- 原始目录名仍含 `XiAn_Test`，必须由 manifest 明确正式区域是武汉。
- T05 Phase2 纯 T11 relation 仍需要空 surface/evidence 兼容路径，是后续可独立治理的接口债。
- 原始数据存在缺失端点引用；本实验不裁剪，并只对 `endpoint_overrides/p02_confirmed_endpoint_overrides.csv` 登记且由用户逐项确认的 9 个 `SNodeId/ENodeId` 属性单元执行临时工作副本覆盖。覆盖后工作副本缺失端点为 0，但该实验白名单不能提升为生产规则，也不能与完整生产基线直接比较。
- `CrossLid` 在本轮不作为 T05/T06 端点改写规则；若需正式启用，必须由独立字段语义任务明确适用范围和冲突处理。
- 用户后续可能补充人工关系；每次补充必须形成新 raw 版本，不覆盖本次原始关系。
- P02 已按 2026-07-14 用户授权登记唯一长期入口 `scripts/p02_run_wuhan_internal_case.py`；该入口绑定当前武汉单 Case 硬校验，不应扩展成通用区域运行器。
- 内网必须提供 QGIS Python 运行时；若无法发现 `python-qgis-ltr` / `python-qgis` 且未显式配置，正式执行会在 QGIS 阶段失败并保留前序审计产物。
