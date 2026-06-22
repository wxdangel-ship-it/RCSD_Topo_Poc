# 06 Risks And Technical Debt

## 1. 文档与契约分层风险

T00 容易被误读为正式预处理模块。当前边界是：T00 保留历史工具和支撑入口；T08 才是 SWSD / RCSD 正式预处理、质检和修复模块。

## 2. 历史命名兼容债

Tool 编号沿用历史命名，且当前没有 Tool8。后续维护时不能因为编号连续性自动补建 Tool8，也不能把 Tool10 / Tool11 的参数驱动形式推广为所有工具的默认模式。

## 3. 数据质量风险

- 历史输入可能缺 CRS、字段不一致或几何无效。
- A200 与 SW 输入存在 CRS 和字段口径差异。
- MIF 源 CRS 缺失时，如果调用方未显式传入 `--default-crs`，必须阻断而不是猜测。

## 4. 运行与性能风险

- 批量 Patch 或 MIF 转换可能产生大量文件和长时间 IO。
- Tool11 若长期走 Python fallback 写出路径，可能无法承受真实大文件。
- 输出覆盖不清晰会造成新旧派生结果混用。

## 5. 入口治理风险

T00 当前入口已经登记在 repo root `scripts/`。新增、删除、重命名或改变工具调用方式时，必须同步 `docs/repository-metadata/entrypoint-registry.md`、`INTERFACE_CONTRACT.md` 和本模块 README。
