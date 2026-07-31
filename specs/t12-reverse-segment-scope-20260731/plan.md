# 实施计划

## 1. 影响面结论

T12 已持有全量 SWSD Segment、原始 1V1 FRCSD Road/Node、T05 anchor audit
和 RCSDIntersection，能够在模块内部完成锚点区间与跨 Segment 覆盖排除。
无需修改 T01–T11、T10 编排、CLI 或入口。

## 2. 实现分层

1. 新增 `reverse_segment_scope.py`：
   - 构建只读 Segment 空间索引；
   - 验证反向路径第一/最后 Road 与双端标准面接触；
   - 剔除端点标准面后逐 Road 评估 Segment 唯一归属；
   - 生成机器可追溯的逐 Road 归属证据。
2. `candidate_audit.py` 只负责接线，不回填归属算法。
3. `review_publish.py` 增加锚点区间和其它 Segment 覆盖专属排除规则。
4. `outputs.py/models.py` 提升 additive schema，并发布字段与 GPKG 证据层。
5. 同步 T12/项目源事实和代码体量台账。

## 3. 数据与几何策略

- 继续使用显式 projected metre processing CRS。
- 路口接触复用现有 Road-surface `1m` 拓扑容差。
- Segment 竞争排序复用正式 T06 ownership 的 `20m / 50m / distance` 顺序，
  但不读取 T06 生成的 owner 结果。
- 路口面内共享几何不参与 Segment owner 判定。
- 并列不使用 Segment ID 裁决，按保准优先排除。

## 4. 风险与控制

- **共享路口误判为跨 Segment 覆盖**：先剔除双端标准面及容差。
- **平行 Segment 归属歧义**：要求唯一最优，歧义不确认。
- **性能下降**：Segment STRtree 一次构建；buffer 延迟缓存；只对反向候选评估。
- **接口回归**：不新增参数，schema 只加字段与证据层。
- **真实 Case 口径变化**：旧 v7 冻结正例被新用户口径明确取代，保留新旧验证记录。

## 5. 验证顺序

1. 写锚点区间、其它 Segment 覆盖和归属歧义失败测试。
2. 实现 helper 与最小接线，跑专项测试。
3. 跑 T12 全量测试和 T10/T12 编排契约测试。
4. 重跑本地 `1026960`，确认 v7 已知误报被排除并核对原两类问题。
5. 双跑比较稳定内容，检查 CSV/GPKG/manifest。
6. 扫描体量、`compileall`、`git diff --check`，记录内网性能待验。
