# 027 - T01 wrapper input role preflight

## 时间

2026-06-14

## 背景

内网全量链路在 `t01` 阶段出现 `ValueError: invalid literal for int() with base 10: '060a'`。运行日志显示包装脚本被调用时把 `nodes.gpkg` 传入了 `<roads_path>`，把 `roads.gpkg` 传入了 `<nodes_path>`，导致 T01 bootstrap 按 road schema 读取 node layer。

## 业务逻辑变更

- `scripts/t01_run_full_data.sh` 在进入 `t01-run-skill-v1` 前读取两个输入 GeoPackage 的首层 schema。
- `<roads_path>` 必须包含 road 拓扑字段 `snodeid/enodeid`。
- `<nodes_path>` 必须包含节点字段 `id`，且不得同时呈现 `snodeid/enodeid` 的 road layer 特征。
- 若两类输入疑似传反，脚本在 T01 bootstrap 前直接阻断，并输出 `roads_path and nodes_path appear to be swapped` 提示。

## 不变项

- 不改变 `t01-run-skill-v1` CLI 契约。
- 不改变 T01 Step1-Step6 的构段规则、字段启用规则或输出 schema。
- 不新增正式执行入口。

## 验证点

- 正确顺序输入应输出 `T01 input role validation passed` 后继续进入 T01。
- 反序输入应在包装脚本内阻断，不再进入 T01 bootstrap。
