# 04 Solution Strategy

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

后续版本再实现道路 / 节点依赖补齐与可复跑数据子集。

多 Case 包保持同一根目录，并按 `cases/<case_id>/` 存放每个 Case 的 manifest、summary 与外部输入。文本 bundle 只负责传输，自动分片和解包不改变 Case 结构。

## 3. Suggest 策略

`suggest` 先从 `prepared_swsd_nodes` 建立语义路口 inventory。可选 selector evidence 用于把 T08 质检错误、T05/T06/T09 失败审计等问题线索映射回 SWSD 语义路口。

没有 selector evidence 时，`suggest` 只能输出 `inventory_only`；有 selector evidence 且命中 CaseID 或 member node 时，输出 `problem_candidate`。

## 4. 与 T08 的关系

T08 的预处理、质检与修复能力作为 T10 外部输入准备前提。T10 不把 T08 纳入 v1 orchestration steps，避免把质量修复链路和业务生产链路混在一个运行职责内。
