# 02 Constraints

## 1. 编排边界

- T10 v1 不改变项目级主业务链。
- T10 v1 不调用 T08。
- T10 v1 不修改 T01-T09 模块算法。
- T10 v1 不替代 T01-T09 的模块级契约。

## 2. 入口约束

当前不新增 repo CLI、`Makefile` 目标、模块 `run.py` 或模块 `__main__.py`。

当前唯一正式 root 脚本入口为 `scripts/t10_pack_innernet_cases.sh`，用于内网多 Case 证据包打包与文本 bundle 分片导出；新增其它稳定入口仍需单独授权并同步入口登记。

## 3. 数据约束

- 所有模块间 handoff 必须以显式文件路径表达。
- Case 范围声明使用 SWSD 语义路口 ID 与半径。
- CaseID 正式含义是 SWSD semantic junction id；坐标只作为由 CaseID 派生的范围中心信息。
- `suggest` 只做候选生成，不判定问题真实性；没有 selector evidence 时只能输出 inventory-only 清单。
- v1 Case package 空间切片 CRS 为 `EPSG:3857`。
- `include_files=true` 的正式默认物化模式为 `spatial_slice`，不得复制全量外部输入冒充 Case 范围证据。
- `manifest_only` 不得表述为空间裁剪成果。
- `copy_full` 仅作兼容诊断模式，不作为正式内网 Case 包默认模式。
