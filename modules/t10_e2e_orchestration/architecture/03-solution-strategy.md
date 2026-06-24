# 03 Solution Strategy

## 1. 契约优先

T10 v1 先解决跨模块契约问题：

- 每个外部输入有稳定 slot。
- 每个模块间产物有稳定 slot。
- 下游不得只传上游目录。
- 缺失、目录型或本机不存在的路径可审计。

## 2. Case 包策略

Case 包 v1 是 spatial-slice-first：

- 用 SWSD 语义路口 ID 和半径表达范围。
- 列出外部输入 slot。
- `include_files=true` 时默认生成局部 GPKG 空间切片。
- `manifest_only` 只声明范围与输入，不物化矢量。
- 明确排除中间产物。
- 空间切片必须补齐被选中 SWSD / RCSD 道路的端点节点，并保留道路完整几何，避免 Case replay 因窗口裁剪丢失拓扑依赖。

多 Case 包保持同一根目录，并按 `cases/<case_id>/` 存放每个 Case 的 manifest、summary 与外部输入。文本 bundle 只负责传输，自动分片和解包不改变 Case 结构。

## 3. Suggest 策略

`suggest` 先从 `prepared_swsd_nodes` 建立语义路口 inventory。可选 selector evidence 用于把 T08 质检错误、T05/T06/T09 失败审计等问题线索映射回 SWSD 语义路口。

没有 selector evidence 时，`suggest` 只能输出 `inventory_only`；有 selector evidence 且命中 CaseID 或 member node 时，输出 `problem_candidate`。

## 4. 与 T08 的关系

T08 的预处理、质检与修复能力作为 T10 外部输入准备前提。T10 不把 T08 纳入 v1 orchestration steps，避免把质量修复链路和业务生产链路混在一个运行职责内。

## 5. Case Runner 策略

T10 Case runner 从 Case package 启动，优先使用 package 内局部切片，按 `T01 -> T07 Step1/2 -> T03 -> T04 -> T05 -> T06 -> T09` 调用既有脚本或模块 callable。

runner 不修改 T01-T09 算法，也不把目录型结果隐式传给下游。每个阶段都记录显式文件输入、输出、命令、stdout log、耗时和状态。

节点状态 handoff 必须连续传递：`t07_nodes` 只表示 T07 Step2 既有路口面锚定结果；T03 运行后发布 `t03_nodes`，T04 必须消费它；T04 运行后发布 `t04_nodes / final_swsd_nodes`，T05 / T06 / T09 必须消费 `final_swsd_nodes`。Relation handoff 则由 T07/T03/T04 evidence 进入 T05，最终由 T05 `intersection_match_all` 统一发布。

T07 Step3 保留为可选兼容 relation 补锚能力，只有在明确提供早期或外部 `intersection_match_all` 兼容 relation 输入时才应运行。它不能被 T10 解释成 T05 之后的默认重锚阶段，也不能替代 T07/T03/T04/T05 的正式 relation 主业务链。

T03 / T04 当前仍基于输入切片自动发现候选 Case，T10 不在本层强行改写候选发现规则，只把发现结果和失败状态作为审计事实记录。

T09 当前没有 repo 主 runner；T10 通过 T09 既有模块 callable 执行 Step1/2，并在 T06 Step3 成功后调用 Step3 F-RCSD restriction 投影。

## 6. T06 漏斗策略

T10 不参与 T06 判定。T10 只读取 T06 Step1 / Step2 / Step3 summary，输出 `t10_t06_funnel.json/csv/md`，用于解释从 SWSD Segment 输入到 F-RCSD 输出的数量流转、拒绝原因和替换质量。
