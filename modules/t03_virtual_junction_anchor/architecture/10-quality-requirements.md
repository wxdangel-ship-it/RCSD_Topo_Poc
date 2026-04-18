# 10 Quality Requirements

- 可审计：每个 case 都有 status、audit、PNG，且 Step45 与 Step67 的机器状态、视觉审计状态可分层回读
- 可批量：Anchor61 必须按 `61 raw / 58 default formal` 稳定落盘
- 可发布：`Step7` 机器状态只允许 `accepted / rejected`
- 可复核：`V1-V5` 继续保留为视觉审计层，且平铺目录与索引可供人工翻阅
- 可诊断：`review / not_established / rejected` 必须给出显式原因与根因分型
- 可治理：模块文档面、项目级盘点、官方入口事实与当前实现保持一致
- 可克制：不把 solver 常量、启发式参数或单轮 closeout 结果误写成长期业务契约
