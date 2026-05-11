# 11 风险与技术债

## 风险

- 真实数据字段名可能存在大小写或命名漂移。
- 右转专用道 / 渠化右转显式字段值依赖调用方通过 `--right-turn-formway-value` 声明确认值；未声明值不会被几何形态反推为强规则。
- T 型主通道 / 侧向判断在缺少可靠方向与配对证据时采用保守策略，输出 ambiguous 而不是强行 through。
- LocalArmCandidate 兜底合并可能掩盖 trace 过度切碎或错误合并；FinalArm validation 通过 relaxed reverse / supplemental trace evidence 暴露 weak、unvalidated 与 conflict 风险，但不替代原始 through 规则。
- A2 无 lineage 证据时主要依赖 A1 输出结构、局部趋势与几何辅助，跨源 ID 不一致时置信度需要 review index 引导人工抽检。
- A2 不自动拆分 over-merged Arm，需通过 ArmBuildFeedback 暴露给 A1 / 数据修复流程。
- P01-Final 不再依赖精确源 Road 匹配作为生成前提；F-RCSD:Road.Source 与 CRS 归一化后的 rounded exact geometry 仅作为审计 / 置信增强证据。Source 缺失、归一化后仍无法匹配或源侧重复几何会进入 issue / 人工复核，不做空间近似兜底。
- `950044` 已确认为 A1 / A2 后续修复 case；当前 A2 输出存在 `source_over_merged_unresolved / conflict` 与 recommended split / merge feedback。
- SWSD basic fallback 只允许稳定基础规则；多平行支路细节、局部 partial 规则或 F-RCSD 中没有承载道路的规则不得静默投影。

## 缓解方式

- 字段读取大小写不敏感。
- 字段缺失写 issue，不反推语义。
- 所有停止点输出 trace 与 decision，供 case 归纳。
- 兜底 FinalArm 输出 `final_arm_validation.json`，并将 validation risk 透传到 corrected_final_arms 与 P01-Final audit。
- 正式入口变更必须走入口登记和契约同步。
- A2 保存所有 candidate 与 selection reason，避免只输出最终配准导致审计断点丢失。
- P01-Final 保存 ArmSourceProfile、SourceArmPassRule、final generation decision、source map、兼容 policy、audit 与 issue，避免 final GeoJSON 无法追溯规则来源。
