# 现状研究与决策

## 1. 当前实现事实

- T12 v9 已支持 Segment 三类与 Junction 三类，Segment/Junction 文件和几何已分层。
- T12 当前参数 `--t07-step3-run-root` 读取 `relation_cardinality_errors.csv/json`，并把 `one_target_to_many_base/many_target_to_one_base` 直接发布。
- 用户审计的 `764857`、`26981804` 来源于该 Step3 广义 relation 审计，但它们不是 T07 Step2 路口锚定失败。
- T07 正式契约明确：Step2 final `fail1` 表示多节点语义路口命中多个 RCSDIntersection；`fail2` 表示一个 RCSDIntersection 对应多个参与 Step2 的语义路口；优先级 `fail2 > fail1`。
- T07 Step2 输出包含 `nodes.gpkg`、`node_error_1.gpkg`、`node_error_2.gpkg`、summary、audit 和 relation evidence。

## 2. 决策

### D-001 来源真值

以 Step2 `nodes.gpkg` 代表路口最终 `is_anchor` 为真值；error GPKG 与 summary 只做强一致性校验。原因是 error1 可以记录 provisional fail1，而 final state 可能被 fail2 覆盖。

### D-002 fail2 分组

以 `node_error_2.gpkg` 中代表路口和 intersection IDs 构建 Junction↔RCSDIntersection 连通分量。同一分量逐 Junction 发布 J04并共享稳定 conflict group。

### D-003 旧参数兼容

新增 `--t07-run-root`。旧 `--t07-step3-run-root` 只允许在一个版本内定位同一 T10 run 下的 Step2 root；找不到时 blocked，绝不读取 cardinality 文件。

### D-004 分类集中化

建立单一 taxonomy 定义和 enrichment 函数；Segment/Junction 输出与 summary 共用，避免类型、中文名称和 repair domain 漂移。

### D-005 excluded/manual 语义

`issue_type` 仍只对 confirmed 非空；所有结果都写 `result_status`。excluded/manual 保留 detection/decision/root evidence，但不伪装为正式错误类型。

## 3. 未修改事项

- 不修改 T07 Step1/Step2/Step3 代码、接口或算法。
- 不改变 T03 Junction 两类重验算法。
- 不改变 Segment carrier、反向归属或 review override 算法。
- 不增加新的正式脚本或 CLI 子命令。
