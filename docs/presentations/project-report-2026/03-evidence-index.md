# 证据索引

本文件记录 PPT 结论、数字、案例和图片的证据来源。没有证据来源的内容只能作为待确认讨论项，不进入正式结论。

## 证据登记模板

| 编号 | 结论或指标 | 证据类型 | 来源路径或说明 | 当前状态 | 对应页码 |
|---|---|---|---|---|---|
| E-000 | 示例：全量融合成功率 | run summary | 待补真实 run root 和 summary 文件 | 待补 | 2, 5 |

## 待补关键证据

| 编号 | 证据项 | 用途 | 当前状态 |
|---|---|---|---|
| E-001 | 全量运行 run root | 支撑成果摘要、漏斗统计、T10 编排说明。 | 待确认。 |
| E-002 | 总输入规模和阶段统计 | 支撑成果漏斗。 | 待确认。 |
| E-003 | 成功构建路口、路段、Movement 的统计 | 支撑道路结构层效果。 | 待确认。 |
| E-004 | T05 路口锚定漏斗 | 支撑路口锚定可消费率、来源贡献和前置损失分析。 | 待确认真实 `t05_junction_anchor_funnel_summary.json`。 |
| E-005 | T05 relation 质量审计 | 支撑 relation 基数错误、blocking error、graph consumability 分析。 | 待确认 `relation_cardinality_errors.*`、`blocking_errors.*`、`relation_graph_consumability_audit.*`。 |
| E-006 | T06 Step1/Step2/Step3 漏斗 | 支撑 Segment 替换率、RCSD 候选构建率、replacement plan ready 率。 | 待确认 `t06_step1_summary.json`、`t06_step2_summary.json`、`t06_step3_summary.json` 或 T10 `t10_t06_funnel.*`。 |
| E-007 | T06 Step3 relation 明细 | 支撑 RCSD 最终替换率、纯替换率、混源保留率、retained / failed 统计。 | 待确认 `t06_step3_swsd_frcsd_segment_relation.*`。 |
| E-013 | T06 problem registry / failure business audit | 支撑 Segment 损失原因、上游回流和质量闭环。 | 待确认 `t06_segment_replacement_problem_registry.*`、`t06_rcsd_segment_failure_business_audit.*`。 |
| E-014 | T06 topology / surface QA | 支撑替换后拓扑质量和 surface-assisted closure 贡献。 | 待确认 `t06_step3_topology_connectivity_audit.*`、`t06_step3_surface_topology_audit.*`。 |
| E-015 | T09 restriction 恢复统计 | 后续通行能力专题证据，暂不纳入 L0 / L1 主指标。 | 待确认 `t09_swsd_field_rule_restoration_summary.json`、`t09_step3_frcsd_restriction_summary.json`。 |
| E-008 | 典型复杂 junction case 图片 | 支撑成果现状与根因分析中的示例页。 | 待选 case。 |
| E-009 | 典型数据缺失或表达不足 case 图片 | 支撑损失原因示例。 | 待选 case。 |
| E-010 | 典型替换风险 case 图片 | 支撑替换门控和保留策略说明。 | 待选 case。 |
| E-011 | 当前测试或验证结果 | 支撑工程质量和可信度说明。 | 待确认。 |
| E-012 | Skill 反馈案例 | 支撑长期质量优化能力说明。 | 待整理。 |

## 证据使用规则

- PPT 中的数字必须登记来源路径、统计口径和生成时间。
- 如果使用旧 baseline 或历史 run，必须标明不是最新全量结果。
- 如果使用人工绘制示意图，必须标明“示意”，不得伪装成真实 case 截图。
- 如果一个结论依赖多个模块，应分别登记每个模块的证据来源。
- 对于质量问题，不只登记现象，还要登记根因和当前处理策略来源。
