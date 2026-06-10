# T10 端到端业务流程编排

> 本文件是 `t10_e2e_orchestration` 的操作者总览。长期源事实以 `architecture/*` 与 `INTERFACE_CONTRACT.md` 为准。

## 1. 模块定位

T10 用于组织 RCSD_Topo 端到端业务链路和 Case 级证据包。T10 v1 编排 `T01 -> T07 -> T03 -> T04 -> T05 -> T06 -> T09`，T08 独立运行，不纳入 v1 编排步骤。

## 2. 运行入口

当前没有 repo 官方 CLI 或 root 脚本入口。模块提供 callable：

```python
from rcsd_topo_poc.modules.t10_e2e_orchestration import (
    build_case_evidence_package,
    write_t10_planning_outputs,
)
```

## 3. 常见运行方式

- 使用 `write_t10_planning_outputs` 生成 workflow plan、handoff audit 与 summary。
- 使用 `suggest_t10_cases` 从 SWSD nodes 与可选 selector evidence 生成候选 Case 列表。
- 使用 `build_case_evidence_package` 生成 Case 证据包 manifest，并可选择复制外部输入文件。
- 使用 `build_multi_case_evidence_package` 一次打包多个 SWSD 语义路口 ID。
- 使用 `export_t10_case_evidence_text_bundle` / `decode_t10_case_evidence_text_bundle` 分片传输并解包恢复 `cases/<case_id>/` 结构。
- 内网一次性打包可参考 `examples/t10_pack_innernet_cases.sh`；该文件是示例脚本，不是 repo 官方入口。

## 4. 输出总览

- `t10_workflow_plan.json`
- `t10_handoff_audit.json`
- `t10_summary.json`
- `t10_case_suggestions.json/csv`
- `t10_case_evidence_manifest.json`
- `t10_case_evidence_summary.json`
- `t10_multi_case_evidence_manifest.json`
- `t10_multi_case_evidence_summary.json`

## 5. 文档阅读顺序

1. `INTERFACE_CONTRACT.md`
2. `architecture/01-introduction-and-goals.md`
3. `architecture/03-context-and-scope.md`
4. `architecture/04-solution-strategy.md`
5. `architecture/10-quality-requirements.md`
