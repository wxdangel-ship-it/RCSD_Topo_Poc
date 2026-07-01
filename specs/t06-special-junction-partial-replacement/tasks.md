# Tasks: T06 特殊路口局部替换策略

## Implementation

- [x] I001 将 `special_junction_gate` 改为 `passed / partial / blocked` 三态。
- [x] I002 移除 partial 组对已可替换 Segment 的 `removed_replaceable_segment_ids` 二次删除。
- [x] I003 让 Step2 summary 输出 `special_junction_group_partial_count`。
- [x] I004 保持只有全通过特殊组才能发布 `special_junction_group_internal` replacement plan。
- [x] I005 同步 T06 模块源事实和 architecture 文档。

## Testing

- [x] T001 增加 partial 复杂组/环岛单元测试。
- [x] T002 增加 partial 环岛 replacement plan 单元测试，确认内部 RCSD Road 不进入计划。
- [x] T003 更新既有 runner 输出断言。
- [x] T004 运行 T06 聚焦单测。
- [x] T005 选择既有复杂路口和全通过特殊组基准 case 做修改前后对比。

## QA Evidence

- [x] Q001 CRS 与坐标变换说明。
- [x] Q002 拓扑一致性说明。
- [x] Q003 几何语义说明。
- [x] Q004 审计可追溯性说明。
- [x] Q005 性能可验证性说明。
