# P05-Scheme-A-Dataset-P1 实施计划

## 阶段 1：冻结合同

1. 固定 T10 Case-level 与 T10-Error/T10-Error-2 target-only 语义。
2. 固定 Case terminal、Segment label、Segment scorer 和 context input 四层资格。
3. 冻结不训练、不改 T01–T12、不新增入口、不提交推送边界。

## 阶段 2：lineage 审计

1. 读取 Dataset-P0 sample manifest 与 Scheme A frozen skeleton。
2. 从每个 Segment 包 manifest 读取 target ID 与冻结 SWSD Road 集合。
3. direct ID 按正式业务身份映射并审计 Road drift；只有 ID 不存在时才校验
   无重叠 exact Road partition。
4. 对任何不完整或歧义映射 hard mask，不用 geometry 猜测。

## 阶段 3：标签合同重建

1. 为 8,863 个当前 Segment输出唯一 scope 行。
2. T10 全量 `CASE_TRUTH_LABEL`。
3. Segment 包后继目标输出 `TARGET_LINEAGE_LABEL`，其它对象输出
   `CONTEXT_ONLY_MASKED`。
4. 分离 expected-failure Case 终态与局部 failure group。
5. 形成旧阶段 metric invalidation ledger。

## 阶段 4：实现与验证

1. 新增 P05 内部只读 callable 与稳定数据模型。
2. 新增 direct/partition/leakage/expected-failure/破坏测试。
3. 执行正式 Run A/B、内容签名、CRS/geometry/拓扑/资源审计。

## 阶段 5：收口

1. 形成 validation summary。
2. 同步 P05 项目级和模块级源事实。
3. 不训练、不提交、不推送。
