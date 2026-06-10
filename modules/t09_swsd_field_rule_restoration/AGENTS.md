# T09 模块级执行规则

本文件只补充 `t09_swsd_field_rule_restoration` 的模块局部规则。仓库级硬规则仍以 repo root `AGENTS.md` 为准。

## 开工前先读

1. `README.md`：先确认模块阅读入口、当前状态和文档职责。
2. `SPEC.md`：理解凝练版业务需求、输入输出和对错边界。
3. `architecture/04-solution-strategy.md`：理解 Step1/2/3 详细业务落地策略。
4. `INTERFACE_CONTRACT.md`：确认稳定输入、输出、callable、参数和验收口径。
5. 涉及上游数据时，回看 T01、T06、T08 的模块契约。

## 模块边界

- T09 负责 SWSD 现场通行规则证据还原，并把显式禁止通行证据投影到 F-RCSD restriction。
- T09 不生成 F-RCSD `RoadNextRoad`。
- T09 不修改 T06、T08、SWSD 或 F-RCSD 输入。
- T09 不根据缺少 allowed evidence 自动推导 prohibited。
- T09 不把 topology not applicable 或 direction incompatible 表达为交通规则禁止。

## 入口规则

- 当前 T09 正式能力由模块内 callable 承载。
- 不新增 repo CLI、root `scripts/`、Makefile 目标、模块 `run.py` 或模块 `__main__.py`，除非任务书单独授权并同步入口登记。
- 现有 `scripts/t09_export_step3_input_text_bundle_innernet.sh` 是已登记的内网 Step3 输入证据包导出脚本，不代表 T09 主 runner 已经成为 repo CLI。

## 修改规则

- 修改 T09 文档时必须保持 `README.md`、`SPEC.md`、`INTERFACE_CONTRACT.md`、`architecture/04-solution-strategy.md` 对齐。
- 修改 T09 实现前必须检查目标 `.py` 文件字节数，遵守 repo root `AGENTS.md` 的 100KB 硬阈值。
- 若需要改变上游 T06 relation、T08 Tool7 / Tool8 输出语义或 T01 Segment 语义，必须停止并回报。

## 完成前检查

- 文档修改至少运行 `git diff --check`。
- 代码修改必须按任务书执行对应测试，并说明未覆盖的 GIS / 拓扑 / 真实数据验证缺口。
