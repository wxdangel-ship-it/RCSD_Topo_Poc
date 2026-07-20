# Implementation Plan：T12 Road-surface portal

## 产品

- 消除正确 T07 1V1 锚定下，node portal 表达不足导致的高置信误报。
- 距离门禁降为可见、可复核的审计风险；不牺牲方向、物理 Road 与唯一锚点门禁。
- 保持 `1026960` 的 10 条冻结质量问题集合不变。

## 架构

- 保留 raw carrier 与现有 portal-constrained semantic carrier，不改变其既有语义。
- 在两者均未排除 candidate 后，增加独立的 T07 Road-surface portal carrier 层。
- 新层使用原始有向 Road 图、唯一 T07 标准面和锚点组一跳 frontier；不修改图和输入几何。
- decision/output 使用独立 evidence basis，避免与旧 semantic carrier 混淆。

## 研发

- 新增小型 `surface_portal_carrier.py`，集中封装 surface access、frontier 与有向最短路径。
- `candidate_audit.py` 只负责调用和合并方向证据；`review_publish.py` 只消费独立排除 basis。
- `models.py`/`outputs.py` 采用加法字段扩展；CLI 参数与入口保持不变。
- 生产源文件禁止对象 ID 和 Case 特判。

## 测试

- 单元测试覆盖 Road 首末与 surface 相交、目标 one-hop frontier、距离超限仍 audit-only、方向错误、无物理 Road、非 T07 不启用、路径长度超限拒绝。
- 重放三条目标 Segment，核对方向和 Road 序列。
- 从原始 `1026960` 输入运行 T12，校验 35/10/25/0 及 confirmed `candidate_id + issue_type` 冻结集合。
- 运行 T12/T10 受影响测试、源码对象 ID 扫描、体量与格式检查。

## QA

- CRS：处理 CRS 必须是 metre-based projected CRS，转换记录沿用 T12 manifest。
- 拓扑：只读原始 Road endpoint/main-sub 关系；缺 endpoint 硬阻断，不 silent fix。
- 几何：分别输出 surface intersection/frontier、长度和距离审计指标。
- 追溯：每方向输出 access kind、surface、Road 序列、frontier 与拒绝原因。
- 性能：仅对已有 candidate 且 T07 双端受信的失败方向运行；记录阶段耗时并与 `1026960` 基线比较。

## 兼容与边界

- 不新增或改变官方入口，因此不触发 entrypoint registry 变更。
- 本轮已获授权更新项目级与 T12 模块级正式源事实和输出契约。
- 若 `1026960` 冻结集合变化，暂停发布并回到原始数据审计，不修改 fixture 迎合实现。
