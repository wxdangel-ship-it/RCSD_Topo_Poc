# 06 风险与技术债

## 当前架构风险

| 风险 | 影响 | 缓解方向 |
|---|---|---|
| 字段语义漂移 | 局部样本反推字段可能污染正式规则 | 字段启用必须写入项目级或模块级源事实，并保留未确认边界 |
| RCSD Laneinfo / 轨迹证据缺失 | T09 对混源路口通行能力还原仍不完整 | 先以 SWSD Laneinfo / restriction 和 F-RCSD 承载关系恢复，再专项补证 |
| 混源 F-RCSD 解释风险 | SWSD Segment 替换后 Road / Node 语义可能难追溯 | T06 / T09 必须保留 source、relation evidence 和审计摘要 |
| 锚定召回与准确率权衡 | 兜底关系提高替换率，但可能引入误关联 | T05 汇总关系时区分正式、兜底、review-only 证据 |
| T06 替换边界复杂化 | RCSD 数据质量和工艺差异导致 T06 同时承担 relation 诊断、补拓扑和替换执行，容易扩大模块职责 | T06 只在 Step2 replacement plan 和 Step3 audit 边界内执行；上游问题通过 problem registry / T10 feedback 回流 |
| Surface-assisted closure 误用 | T03/T04/T05/T07 surface 证据若被当成替换白名单，可能绕过 T04 reject 或多候选冲突 | Surface closure 只补节点语义或 relation node map，不新增正式替换道路，不改写原始道路几何 |
| 提前右转与保留 SWSD carrier 混源 | 提高通行 carrier 保留率的同时可能模糊正式替换道路来源 | `frcsd_road_ids` 只描述正式 RCSD 替换清单，保留 SWSD carrier 通过 `replaced+retained_swsd` 和风险标记单独暴露 |
| T10 feedback 自动回灌过度 | 上游反馈若直接驱动替换，可能绕过 T03/T04/T05/T06 正式审计 | T10 feedback 只回灌可消费 endpoint candidate 或形成上游任务，不作为 T06 Step3 替换白名单 |
| T09 通行证据缺口 | T09 已具备模块文档面，但 RCSD Laneinfo 与轨迹通行证据仍不足 | 后续专项补充 RCSD Laneinfo / 轨迹证据，并同步 T09 契约 |
| T02 历史入口仍在 | Retired 生命周期与真实脚本入口容易混淆 | 后续入口治理中同步 retired / historical 口径 |

## 可接受技术债

- 当前保留 T00 / T02 历史支撑入口，以满足追溯和局部工具复用。
- P01 作为 POC / 成果模块存在，不进入 T09 正式契约。
- 旧 `TEXT_QC_BUNDLE` 相关 CLI 入口保留为兼容工具，但不再作为正式协作协议。
- `docs/doc-governance/audits/` 保留历史审计材料，其中旧文件名和旧口径仅作追溯，不作为当前源事实。
- T06 当前同时保留 problem registry、visual check、topology audit 和 surface topology audit 多类质量证据；短期接受证据类型较多，后续应沉淀成更稳定的批量质量看板。
