# 11 风险与技术债

## 当前风险

- 真实数据字段名可能存在大小写或命名漂移。
- 右转专用道字段值尚未在项目级统一冻结；当前实现只能对 `--right-turn-formway-value` 显式传入的已确认值保守排除。
- T 型主通道 / 侧向判断在缺少可靠方向与配对证据时会偏保守，输出 ambiguous 而不是强行 through。
- 真实数据规模与字段完整性尚未在本轮验证。
- A2 第一版无 lineage 证据时主要依赖 A1 输出结构、局部趋势与几何辅助，跨源 ID 不一致时置信度仍需 review index 引导人工抽检。
- A2 当前不自动拆分 over-merged Arm，后续需基于 case 反馈归纳 A1 或 A2 规则。
- P01-Final 当前依赖 F-RCSD:Road.Source 与几何完全一致；Source 缺失、几何微小漂移或源侧重复几何会进入 issue / 人工复核，不做空间近似兜底。
- RCSD -> SWSD fallback 只实现当前授权的异常场景，其它跨源补关系必须等待后续业务确认。

## 缓解方式

- 字段读取大小写不敏感。
- 字段缺失写 issue，不反推语义。
- 所有停止点输出 trace 与 decision，供后续 case 归纳。
- 后续如需正式 CLI，走入口登记和契约同步。
- A2 保存所有 candidate 与 selection reason，避免只输出最终配准导致审计断点丢失。
- P01-Final 保存 source map、policy、audit 与 issue，避免 final GeoJSON 无法追溯来源。
