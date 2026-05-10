# 11 风险与技术债

## 风险

- 真实数据字段名可能存在大小写或命名漂移。
- 右转专用道 / 渠化右转显式字段值依赖调用方通过 `--right-turn-formway-value` 声明确认值；未声明值不会被几何形态反推为强规则。
- T 型主通道 / 侧向判断在缺少可靠方向与配对证据时采用保守策略，输出 ambiguous 而不是强行 through。
- A2 无 lineage 证据时主要依赖 A1 输出结构、局部趋势与几何辅助，跨源 ID 不一致时置信度需要 review index 引导人工抽检。
- A2 不自动拆分 over-merged Arm，需通过 ArmBuildFeedback 暴露给 A1 / 数据修复流程。
- P01-Final 依赖 F-RCSD:Road.Source 与几何完全一致；Source 缺失、几何微小漂移或源侧重复几何会进入 issue / 人工复核，不做空间近似兜底。
- RCSD -> SWSD fallback 仅覆盖 P01 v1.0.0 定义的异常场景，其它跨源补关系需要需求基准授权。

## 缓解方式

- 字段读取大小写不敏感。
- 字段缺失写 issue，不反推语义。
- 所有停止点输出 trace 与 decision，供 case 归纳。
- 正式入口变更必须走入口登记和契约同步。
- A2 保存所有 candidate 与 selection reason，避免只输出最终配准导致审计断点丢失。
- P01-Final 保存 source map、policy、audit 与 issue，避免 final GeoJSON 无法追溯来源。
