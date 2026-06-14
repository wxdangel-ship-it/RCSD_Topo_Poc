# 004 - 扁平多 Case package 发现

- 日期：2026-06-11
- 模块：T10 E2E orchestration
- 变更类型：Case runner 输入目录兼容

## 背景

T10 端到端测试数据可由打包工具恢复为 `cases/<case_id>/` 结构，也可能以测试数据根目录直接承载多个 `<case_id>/t10_case_evidence_manifest.json` 子目录。后者来自按 Case 分目录沉淀的外部测试数据，不改变 Case manifest、外部输入 slot 或模块间 handoff 语义。

旧版 Case runner 只识别标准 `cases/<case_id>/` 与单 Case 根目录。当用户直接传入扁平多 Case 根目录时，runner 会报告找不到 Case，导致必须临时创建 `cases/` 包装目录才能执行全链路验证。

## 业务逻辑变更

`run_t10_e2e_cases_from_package` 的 Case 发现规则调整为：

1. 若 `package_dir/cases/` 存在，仍优先按标准多 Case package 读取。
2. 若 `package_dir/t10_case_evidence_manifest.json` 存在，仍按单 Case 根目录读取。
3. 否则扫描 `package_dir` 的直接子目录，只接收包含 `t10_case_evidence_manifest.json` 的目录作为 Case。
4. `case_id` 过滤仍按 Case 目录名执行，不读取或推断额外业务字段。

该变更只扩展 package 目录布局识别，不新增执行入口，不改变 T01-T09 的调用链、输入字段语义、CRS 处理、拓扑修复策略或输出合同。

## 质量与审计

- CRS 与坐标变换：仍由各阶段模块处理，T10 只传递 manifest 声明的输入路径。
- 拓扑一致性：不新增 silent fix，不改变任何拓扑构建或替换规则。
- 几何语义：不读取几何字段，不根据目录结构推断道路、路口或限制含义。
- 审计可追溯性：runner manifest 继续记录实际 `package_dir`、Case 目录、阶段输入输出与日志。
- 性能可验证性：Case 发现仅扫描 `package_dir` 的直接子目录，复杂度与 Case 数量线性相关。

## 验证

- 补充单元测试覆盖扁平多 Case 根目录发现、无 manifest 子目录忽略、`case_id` 过滤。
- 使用真实 T10 测试数据根目录执行受控 smoke，确认无需临时 `cases/` 包装目录即可进入链路。
