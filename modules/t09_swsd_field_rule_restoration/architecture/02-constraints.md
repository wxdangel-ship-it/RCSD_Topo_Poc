# 02 Constraints

## 1. 业务约束

- 只有显式 restriction 能把 Movement 判定为禁止通行。
- 缺少 allowed evidence 不等于 prohibited。
- topology not applicable 和 direction incompatible 不是交通规则禁止。
- arrow 与 special carrier 证据不得在无 restriction 时单独生成禁止规则。

## 2. 数据约束

- SWSD Node / Road、T01 Segment、T08 Tool7 / Tool8、T06 Step3 输出均作为只读输入。
- F-RCSD Road / Node 必须保留 `source`，但 T09 不能用 `source` 反推限制语义。
- Step3 必须使用 T06 `t06_step3_swsd_frcsd_segment_relation`，不能依赖 Road ID 同名假设。

## 3. 入口约束

- 当前不新增 repo CLI、root `scripts/` 或 Makefile 目标。
- 模块能力通过 callable 暴露。
- 已登记的 T09 Step3 输入证据包脚本只作为证据包辅助入口。
