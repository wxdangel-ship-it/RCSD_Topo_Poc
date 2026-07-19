# t12_frcsd_quality_audit

本文件是 T12 的模块阅读入口。T12 对原始 1V1 匹配生成的 FRCSD 做只读通行质量审计，不执行自动修复。

## 1. 当前状态

- 生命周期：`Active`。
- 主职责：用 SWSD 的必需通行方向检查原始 1V1 FRCSD 的局部/全图 carrier，以 raw endpoint topology 为主、portal-constrained semantic carrier 为误报排除门禁，结合标准路口 portal 和锚点可信度自动发布高置信问题；外部复核仅作可选 QA 覆盖。
- 上游：T01 SWSD Segment/Road、T04 final SWSD Node、T05 relation 审计、T06 Step2 交叉证据、RCSDIntersection、原始 1V1 FRCSD。
- 下游：质量复核、FRCSD 数据生产反馈；T10 可将 T12 编排为 audit-only 阶段。

## 2. 文档索引

- [SPEC.md](SPEC.md)：模块需求和正确性口径。
- [INTERFACE_CONTRACT.md](INTERFACE_CONTRACT.md)：稳定输入、输出、状态和入口。
- `architecture/01~06`：上下文、模型、策略、证据、质量和风险。

## 3. 当前入口

- 无 repo CLI 子命令。
- root script：`.venv/bin/python scripts/t12_run_frcsd_quality_audit.py --help`。
- callable：`run_t12_frcsd_quality_audit(...)`。
- T10 full/profile：混合 CRS 输入必须显式设置 `T12_PROCESSING_CRS=<projected metre CRS>`，由 T10 透传为本模块的 `--processing-crs`；不设置时保持硬阻断。

## 4. 阅读顺序

1. `SPEC.md`
2. `architecture/01-introduction-and-goals.md`
3. `architecture/02-data-and-domain-model.md`
4. `architecture/03-solution-strategy.md`
5. `architecture/04-evidence-and-audit.md`
6. `architecture/05-quality-requirements.md`
7. `architecture/06-risks-and-technical-debt.md`
8. `INTERFACE_CONTRACT.md`
