# Implementation Plan：T12 误判审计与高置信规则收敛

## 产品

- 逐条输出 11 个 Segment 的真实问题、误判或不可判断结论。
- 正式结果以准确率为主，证据不足不自动确认。
- `1026960` 的 10 个冻结真值默认保持不变。

## 架构

- 先用正式 T10/T12 流水线从每个 Segment 包重建 T01→T07→T03→T04→T05→T06→T12 证据。
- 将 raw carrier 状态拆成 local/full、directed/undirected，并在 raw failure 后增加 portal-constrained semantic carrier；分别保留路径缺失、阈值拒绝、端点不受信和内部 alias gap 超限原因。
- decision 层只有在 raw carrier 失败且没有受信 semantic 替代路径时，才消费“必需 carrier 真正缺失”的高置信证据。

## 研发

- 优先修复 `candidate_audit.py` 的证据表达和 `review_publish.py` 的自动确认门禁。
- 必要时扩展 models/outputs，但不新增入口、不改变既有必选参数。
- 生产逻辑禁止对象 ID 特判，所有阈值保持参数化和可审计。

## 测试

- 单元测试覆盖 raw failure 被受信 semantic carrier 排除、T07 标准面外 alias、内部 alias gap 超限、真实缺路和方向缺失。
- 11 个 Segment 做数据回归；无法重建项单列，不纳入真假统计。
- `1026960` 使用原始数据跑完整无 review 回归，并校验冻结集合。
- 运行 T10/T12 受影响测试和生产源码 ID 扫描。

## QA

- CRS：显式统一到 metre-based projected CRS 并记录转换。
- 拓扑：缺失 endpoint/无效几何硬阻断，不 silent fix。
- 几何：记录 SWSD 走廊、FRCSD 路径长度、比例、附加长度和最大偏离。
- 追溯：记录输入指纹、参数、每 Segment stage/status、结论与原因。
- 性能：记录重建和 T12 分阶段耗时，并与现有基线比较。

## 兼容与边界

- 不改变正式入口和 T10 阶段顺序，因此不更新 entrypoint registry。
- 已取得用户继续执行授权，并同步更新项目/T12 源事实、模块契约和实现；不改变入口或 T10 阶段顺序。
